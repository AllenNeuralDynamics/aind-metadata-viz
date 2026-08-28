"""FastAPI router for the verification graph.

Read endpoints are anonymous: anyone can open the graph page, click a
statement, and reach the exact code, environment, data references and run
logs behind it. Write endpoints require an ORCID login, reached from the data
portal through its same-origin ``/metadata-viz`` nginx proxy - the portal's
wildcard CORS cannot carry cookies, so cross-origin writes are not an option.

Nodes are authored by agents running on the *client's* machine (see the
``skills/verification-graph`` folder in the data portal's repo), which reach
these endpoints like any other client. The server owns storage, validation and
verification; it does not run an LLM.

Promotion out of ``proposed`` is deliberately narrow: an admin can approve a
node only once its code gates and its reproducibility run have passed, and the
reproducibility run is executed *here*, in a sandbox, not taken on trust from
whoever submitted the node. See /docs (Swagger UI) for full schemas.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from ..auth import require_admin, require_user
from . import runner as runner_mod
from . import store
from .graph import (
    filter_by_status,
    mark_descendants_stale,
    now_iso,
    subgraph,
    validate_node,
)
from .jobs import queue
from .models import (
    AXIS_NAMES,
    AnyNodeCreate,
    CodeListing,
    GraphSnapshot,
    JobStatus,
    VerifyBatchRequest,
    VerifyBatchResult,
    VerifyRequest,
)

_logger = logging.getLogger(__name__)

verification_router = APIRouter(prefix="/verification", tags=["verification"])

MAX_CODE_UPLOAD_BYTES = store.MAX_CODE_FILE_BYTES

#: Per-call cap on POST /verify-batch, generous enough for "verify everything"
#: on a graph with thousands of nodes while still bounding one request's size.
MAX_VERIFY_BATCH = 5000


def _slug(text: str) -> str:
    """Return a lowercase, hyphenated, S3-key-safe slug of *text*."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return cleaned[:64] or uuid.uuid4().hex[:8]


def _generate_id(doc: dict) -> str:
    """Return a stable id for a new node, derived from its kind and label."""
    kind = doc.get("kind")
    if kind == "entity":
        return f"ent-{_slug(doc.get('entity_type'))}-{_slug(doc.get('label'))}"
    if kind == "relation":
        return f"rel-{_slug(doc.get('label'))}"
    return f"stmt-{uuid.uuid4().hex[:16]}"


def _error(status: int, message: str) -> JSONResponse:
    """Return the portal's standard error envelope."""
    return JSONResponse(status_code=status, content={"error": message})


# --------------------------------------------------------------------------
# Read endpoints (anonymous)
# --------------------------------------------------------------------------


@verification_router.get(
    "/graph",
    response_model=GraphSnapshot,
    summary="Get the compiled verification graph",
    description=(
        "Returns the whole-graph snapshot: every node summarized (label, status, the four "
        "verification axes, derivation depth) plus every edge. Small enough for the demo graph "
        "to load in one GET. `status` keeps only statements whose *effective* status matches "
        "(a statement is only verified if everything it depends on is too); `root` keeps only "
        "the subgraph reachable from one node - its triple and everything beneath it."
    ),
)
async def graph_get(
    status: Optional[str] = Query(default=None, description="Keep only statements with this effective status"),
    root: Optional[str] = Query(default=None, description="Keep only the subgraph reachable from this node id"),
):
    """Return the compiled snapshot, optionally filtered by status or root."""
    try:
        snapshot = await asyncio.to_thread(store.get_snapshot)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("GET /verification/graph")
        return _error(500, str(exc))

    if root:
        snapshot = subgraph(snapshot, root)
    if status:
        snapshot = filter_by_status(snapshot, status)
    return snapshot


@verification_router.get(
    "/manifest",
    summary="Get the compact node index",
    description="Returns `[{id, kind, label, status, updated}, ...]` for every node - the index "
    "a locally-run authoring agent searches for reusable nodes before writing new ones.",
)
async def manifest_get():
    """Return the compact id -> summary index."""
    try:
        return JSONResponse(content=await asyncio.to_thread(store.get_manifest))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("GET /verification/manifest")
        return _error(500, str(exc))


@verification_router.get(
    "/nodes/{node_id}",
    summary="Get one node document",
    description="Returns the full node document: the triple, the value, the dependencies, the "
    "verification record with per-axis run details, and the provenance history. 404 if unknown.",
)
async def node_get(node_id: str):
    """Return one node's full document."""
    try:
        doc = await asyncio.to_thread(store.get_node, node_id)
    except store.InvalidId as exc:
        return _error(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("GET /verification/nodes/%s", node_id)
        return _error(500, str(exc))
    if doc is None:
        return _error(404, f"no node '{node_id}'")
    return JSONResponse(content=doc)


@verification_router.get(
    "/nodes/{node_id}/code",
    summary="List or fetch a node's code sidecar",
    description=(
        "Without `path`, returns the file listing plus the node's `code_hash` and the results of "
        "the layout gates (required files present, known cases counted). With `path`, returns "
        "that one file's contents as plain text, so the UI can show the analysis source."
    ),
)
async def node_code_get(
    node_id: str,
    path: Optional[str] = Query(default=None, description="Fetch one file instead of the listing"),
):
    """Return a node's code listing, or one file from it."""
    try:
        if path:
            data = await asyncio.to_thread(store.get_code_file, node_id, path)
            if data is None:
                return _error(404, f"no file '{path}' for node '{node_id}'")
            return Response(content=data, media_type="text/plain; charset=utf-8")

        files = await asyncio.to_thread(store.load_code_dir, node_id)
    except store.InvalidId as exc:
        return _error(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("GET /verification/nodes/%s/code", node_id)
        return _error(500, str(exc))

    listing = CodeListing(
        node_id=node_id,
        files=[{"path": name, "size": len(data)} for name, data in sorted(files.items())],
        code_hash=runner_mod.code_hash(files) if files else None,
        gates=runner_mod.check_code_layout(files) if files else {},
    )
    return listing


@verification_router.get(
    "/nodes/{node_id}/runs",
    summary="Get a node's verification run history",
    description="Returns every recorded run, newest first, each with its axis, timestamp, "
    "code_hash, result_hash, gate results, and the S3 prefix of its log.",
)
async def node_runs_get(node_id: str):
    """Return a node's run history."""
    try:
        return JSONResponse(content=await asyncio.to_thread(store.list_runs, node_id))
    except store.InvalidId as exc:
        return _error(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("GET /verification/nodes/%s/runs", node_id)
        return _error(500, str(exc))


@verification_router.get(
    "/nodes/{node_id}/history",
    summary="Get a node document's version history",
    description="Returns previous versions of the node document, newest first. Each write "
    "archives the version it replaced, mirroring how contributions are versioned.",
)
async def node_history_get(node_id: str):
    """Return previous versions of a node document."""
    try:
        return JSONResponse(content=await asyncio.to_thread(store.get_history, node_id))
    except store.InvalidId as exc:
        return _error(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("GET /verification/nodes/%s/history", node_id)
        return _error(500, str(exc))


# --------------------------------------------------------------------------
# Write endpoints (ORCID session required)
# --------------------------------------------------------------------------


def _provenance(author: str, action: str, detail: Optional[str] = None) -> dict:
    """Build a fresh provenance block for a newly created node."""
    stamp = now_iso()
    return {
        "author": author,
        "created": stamp,
        "updated": stamp,
        "history": [{"at": stamp, "author": author, "action": action, "detail": detail}],
    }


def _apply_server_owned_fields(doc: dict, orcid: str) -> None:
    """Stamp the fields the server owns, discarding whatever the client sent.

    A caller cannot declare its own node verified, nor claim an axis it never
    ran: statements always enter as ``proposed`` with every axis
    ``not_attempted`` unless the body explicitly declared one.
    """
    if doc.get("kind") == "statement":
        doc["status"] = "proposed"
        if not doc.get("verification"):
            doc["verification"] = {axis: {"status": "not_attempted"} for axis in AXIS_NAMES}
    doc["provenance"] = _provenance(orcid, "created")


@verification_router.post(
    "/nodes",
    summary="Propose a new node",
    description=(
        "Requires an ORCID login. Creates an entity, relation or statement in `proposed` status. "
        "The server assigns the id, validates the triple against the relation's signature, and "
        "rejects dangling or cyclic `depends_on` references. Server-owned fields (`status`, "
        "`provenance`, run records) in the body are ignored. 409 if the id is already taken."
    ),
)
async def node_post(request: Request, body: AnyNodeCreate):
    """Create a node in ``proposed`` status."""
    user = require_user(request)
    doc = body.model_dump(exclude_none=False)
    doc["id"] = doc.get("id") or _generate_id(doc)

    try:
        store.safe_id(doc["id"])
    except store.InvalidId as exc:
        return _error(400, str(exc))

    try:
        existing = await asyncio.to_thread(store.nodes_by_id)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("POST /verification/nodes")
        return _error(500, str(exc))

    if doc["id"] in existing:
        return _error(409, f"node '{doc['id']}' already exists")

    error = validate_node(doc, {**existing, doc["id"]: doc})
    if error:
        return _error(400, error)

    _apply_server_owned_fields(doc, user["orcid"])

    try:
        await asyncio.to_thread(store.put_node, doc)
        await asyncio.to_thread(store.recompile)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("POST /verification/nodes id=%s", doc["id"])
        return _error(500, str(exc))
    return JSONResponse(status_code=201, content=doc)


@verification_router.post(
    "/nodes/{node_id}/code",
    summary="Upload a file into a node's code sidecar",
    description=(
        "Requires an ORCID login. The request body is one file's raw bytes, stored at `path` "
        "inside the node's code directory. Upload `analysis.py`, `test_analysis.py`, "
        "`known_cases.json` and `environment.lock`; the response reports which of the required "
        "layout files are still missing. Changing `analysis.py` or `environment.lock` changes "
        "the node's `code_hash`, which marks its reproducibility stale until it is re-run."
    ),
)
async def node_code_post(
    request: Request,
    node_id: str,
    path: str = Query(..., description="Path inside the code directory, e.g. 'analysis.py'"),
):
    """Store one file in a node's code sidecar."""
    user = require_user(request)
    data = await request.body()
    if not data:
        return _error(400, "request body is required")
    if len(data) > MAX_CODE_UPLOAD_BYTES:
        return _error(400, f"file is {len(data)} bytes; limit is {MAX_CODE_UPLOAD_BYTES}")

    try:
        doc = await asyncio.to_thread(store.get_node, node_id)
        if doc is None:
            return _error(404, f"no node '{node_id}'")
        await asyncio.to_thread(store.put_code_file, node_id, path, data)
        files = await asyncio.to_thread(store.load_code_dir, node_id)
    except store.InvalidId as exc:
        return _error(400, str(exc))
    except ValueError as exc:
        return _error(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("POST /verification/nodes/%s/code path=%s", node_id, path)
        return _error(500, str(exc))

    await _record_code_change(doc, files, user["orcid"])
    return JSONResponse(
        content={
            "node_id": node_id,
            "path": path,
            "bytes": len(data),
            "code_hash": runner_mod.code_hash(files),
            "gates": runner_mod.check_code_layout(files),
        }
    )


async def _record_code_change(doc: dict, files: dict, orcid: str) -> None:
    """Mark a node stale when its code moved away from the last verified hash."""
    if not runner_mod.code_is_stale(doc, files):
        return
    doc.setdefault("code", f"code/{doc['id']}/")
    if doc.get("kind") == "statement" and doc.get("status") == "verified":
        doc["status"] = "stale"
    reproducible = (doc.setdefault("verification", {})).setdefault("reproducible", {})
    reproducible["status"] = "stale"
    doc.setdefault("provenance", {}).setdefault("history", []).append(
        {"at": now_iso(), "author": orcid, "action": "code_changed", "detail": "reproducibility marked stale"}
    )
    await asyncio.to_thread(store.put_node, doc)
    await _propagate_staleness(doc["id"])


async def _propagate_staleness(node_id: str) -> None:
    """Mark every statement deriving from *node_id* stale, then recompile."""
    nodes = await asyncio.to_thread(store.nodes_by_id)
    touched = mark_descendants_stale(nodes, node_id)
    for touched_id in touched:
        await asyncio.to_thread(store.put_node, nodes[touched_id])
    await asyncio.to_thread(store.recompile)


@verification_router.post(
    "/nodes/{node_id}/verify",
    response_model=JobStatus,
    summary="Request a verification run for one axis",
    description=(
        "Requires an ORCID login. Body: `{\"axis\": \"reproducible\"}`. Queues a sandboxed run "
        "that downloads the node's declared data, builds its pinned environment, runs the test "
        "suite with a 100% coverage gate and the known cases, then runs `analysis.py`. The "
        "outcome updates the node's verification record and is written to `runs/`. Jobs run one "
        "at a time; poll `GET /verification/jobs/{job_id}`."
    ),
)
async def node_verify_post(request: Request, node_id: str, body: VerifyRequest):
    """Queue a verification run for one axis of a node."""
    user = require_user(request)
    try:
        doc = await asyncio.to_thread(store.get_node, node_id)
    except store.InvalidId as exc:
        return _error(400, str(exc))
    if doc is None:
        return _error(404, f"no node '{node_id}'")
    if not doc.get("code"):
        return _error(400, f"node '{node_id}' has no code sidecar to run")

    record = await queue.submit(
        "verify",
        lambda: _run_verification(node_id, body.axis, user["orcid"]),
        node_id=node_id,
        axis=body.axis,
        orcid=user["orcid"],
    )
    return record


@verification_router.post(
    "/verify-batch",
    response_model=VerifyBatchResult,
    summary="Queue verification runs for many nodes at once",
    description=(
        "Requires an ORCID login. Body: `{\"node_ids\": [...]}`, or omit `node_ids` (optionally with "
        "`\"status\": \"proposed\"`) to target every eligible node in the graph. A node with no code "
        "sidecar, or already queued/running for this axis, is skipped rather than queued again - safe "
        "to call repeatedly. Jobs still run one at a time server-side (see `jobs.py`); this only saves "
        f"one HTTP round trip per node. Capped at {MAX_VERIFY_BATCH} nodes per call."
    ),
)
async def verify_batch_post(request: Request, body: VerifyBatchRequest):
    """Queue a verification run for every eligible node matching the request."""
    user = require_user(request)
    nodes = await asyncio.to_thread(store.nodes_by_id)

    if body.node_ids is not None:
        if len(body.node_ids) > MAX_VERIFY_BATCH:
            return _error(400, f"at most {MAX_VERIFY_BATCH} node_ids per call")
        targets = [(node_id, nodes.get(node_id)) for node_id in body.node_ids]
    else:
        eligible = [doc for doc in nodes.values() if doc.get("code")]
        if body.status is not None:
            eligible = [doc for doc in eligible if doc.get("status") == body.status]
        if len(eligible) > MAX_VERIFY_BATCH:
            return _error(
                400,
                f"{len(eligible)} nodes match; at most {MAX_VERIFY_BATCH} per call "
                "- narrow with node_ids or status",
            )
        targets = [(doc["id"], doc) for doc in eligible]

    queued: List[dict] = []
    skipped: List[Dict[str, str]] = []
    for node_id, doc in targets:
        if doc is None:
            skipped.append({"node_id": node_id, "reason": "no such node"})
        elif not doc.get("code"):
            skipped.append({"node_id": node_id, "reason": "no code sidecar"})
        elif queue.pending(node_id, body.axis):
            skipped.append({"node_id": node_id, "reason": "already queued or running"})
        else:
            record = await queue.submit(
                "verify",
                lambda node_id=node_id: _run_verification(node_id, body.axis, user["orcid"]),
                node_id=node_id,
                axis=body.axis,
                orcid=user["orcid"],
            )
            queued.append(record)

    return {"queued": queued, "skipped": skipped}


def _run_verification(node_id: str, axis: str, orcid: str) -> dict:
    """Blocking body of a verification job: run, record, propagate, recompile."""
    doc = store.get_node(node_id)
    if doc is None:  # pragma: no cover - the node existed when the job was queued
        raise RuntimeError(f"node '{node_id}' disappeared before its run started")

    files = store.load_code_dir(node_id)
    record = runner_mod.verify_node(doc, files, axis=axis)
    record["log_prefix"] = store.put_run(node_id, record["stamp"], record, record.get("log") or "")

    runner_mod.apply_run(doc, record)
    doc.setdefault("provenance", {}).setdefault("history", []).append(
        {
            "at": now_iso(),
            "author": orcid,
            "action": f"verify:{axis}",
            "detail": record.get("note"),
        }
    )
    store.put_node(doc)

    nodes = store.nodes_by_id()
    for touched_id in mark_descendants_stale(nodes, node_id):
        store.put_node(nodes[touched_id])
    store.recompile()

    return {
        "node_id": node_id,
        "axis": axis,
        "passed": record.get("passed"),
        "note": record.get("note"),
        "stage": record.get("stage"),
        "result_hash": record.get("result_hash"),
        "log": record.get("log_prefix"),
    }


@verification_router.post(
    "/nodes/{node_id}/approve",
    summary="Promote a node from proposed to verified",
    description=(
        "Admin only. Refuses unless the node's code sidecar meets the required layout and its "
        "reproducible axis has passed - a node whose tests are red, whose coverage is under "
        "100%, or which has no passing known case cannot be promoted. Note that approval sets "
        "the node's *stored* status; its effective status is still capped by the worst status "
        "among everything it depends on."
    ),
)
async def node_approve_post(request: Request, node_id: str):
    """Promote a node out of ``proposed`` once its gates and run have passed."""
    user = require_admin(request)
    try:
        doc = await asyncio.to_thread(store.get_node, node_id)
    except store.InvalidId as exc:
        return _error(400, str(exc))
    if doc is None:
        return _error(404, f"no node '{node_id}'")
    if doc.get("kind") != "statement":
        return _error(400, "only statement nodes carry a status to approve")

    files = await asyncio.to_thread(store.load_code_dir, node_id)
    gates = runner_mod.check_code_layout(files)
    if not gates["ok"]:
        return _error(409, f"code gates not met: {gates['missing'] or gates['errors']}")

    reproducible = (doc.get("verification") or {}).get("reproducible") or {}
    if reproducible.get("status") != "passed":
        return _error(409, "the reproducible axis has not passed; run a verification first")

    doc["status"] = "verified"
    doc.setdefault("provenance", {}).setdefault("history", []).append(
        {"at": now_iso(), "author": user["orcid"], "action": "approved", "detail": None}
    )
    try:
        await asyncio.to_thread(store.put_node, doc)
        await asyncio.to_thread(store.recompile)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("POST /verification/nodes/%s/approve", node_id)
        return _error(500, str(exc))
    return JSONResponse(content=doc)


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


@verification_router.get(
    "/jobs",
    response_model=List[JobStatus],
    summary="List recent verification jobs",
    description=(
        "Anonymous read, matching the rest of the graph. Newest first, optionally filtered by "
        "`state` (queued/running/done/failed). This is the recent-activity window backing the "
        "jobs panel - the durable per-node history lives at /nodes/{id}/runs."
    ),
)
async def jobs_get(
    state: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=200),
):
    """Return recent job records, newest first."""
    return queue.list(state=state, limit=limit)


@verification_router.get(
    "/jobs/{job_id}",
    response_model=JobStatus,
    summary="Get a job's status",
    description="Returns the lifecycle state of a queued verification run, plus its result "
    "once it finishes. Poll this after POSTing to /nodes/{node_id}/verify.",
)
async def job_get(job_id: str):
    """Return one job's status record."""
    record = queue.get(job_id)
    if record is None:
        return _error(404, f"no job '{job_id}'")
    return record
