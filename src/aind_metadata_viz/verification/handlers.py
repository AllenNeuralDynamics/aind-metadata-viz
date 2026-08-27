"""FastAPI router for the verification graph.

Read endpoints are anonymous: anyone can open the graph page, click a
statement, and reach the exact code, environment, data references and run
logs behind it. Write endpoints require an ORCID login, reached from the data
portal through its same-origin ``/metadata-viz`` nginx proxy - the portal's
wildcard CORS cannot carry cookies, so cross-origin writes are not an option.

Promotion out of ``proposed`` is deliberately narrow: an admin can approve a
node only once its code gates and its reproducibility run have passed. See
/docs (Swagger UI) for full schemas.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from ..auth import require_admin, require_user
from ..chat.ratelimit import RateLimiter
from . import agent as agent_mod
from . import runner as runner_mod
from . import store
from .graph import (
    compile_manifest,
    filter_by_status,
    mark_descendants_stale,
    now_iso,
    subgraph,
    validate_node,
)
from .jobs import queue
from .models import (
    AXIS_NAMES,
    AgentJobRequest,
    AnyNodeCreate,
    CodeListing,
    GraphSnapshot,
    JobStatus,
    SteerRequest,
    VerifyRequest,
)

_logger = logging.getLogger(__name__)

verification_router = APIRouter(prefix="/verification", tags=["verification"])

#: Agent jobs are expensive; one per user per minute, twenty a day.
agent_rate_limiter = RateLimiter(per_minute=1, per_day=20, burst=1)

MAX_CODE_UPLOAD_BYTES = store.MAX_CODE_FILE_BYTES


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
    "the agent searches for reusable nodes before authoring new ones.",
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
    summary="List the caller's jobs",
    description=(
        "Requires an ORCID login. Returns the caller's own verification and agent jobs, newest "
        "first; admins see everyone's. `kind` narrows to `verify` or `agent`, and `active=true` "
        "to jobs still queued or running. This is how a reloaded page finds a session that is "
        "still going, since job ids are held in memory and not otherwise discoverable."
    ),
)
async def jobs_get(
    request: Request,
    kind: Optional[str] = Query(default=None, description="Narrow to 'verify' or 'agent'"),
    active: bool = Query(default=False, description="Only jobs still queued or running"),
):
    """Return the caller's jobs, newest first."""
    user = require_user(request)
    records = queue.list_jobs(kind)
    if not user.get("is_admin"):
        records = [r for r in records if r.get("orcid") == user["orcid"]]
    if active:
        records = [r for r in records if r.get("state") in ("queued", "running")]
    return records


@verification_router.get(
    "/jobs/{job_id}",
    response_model=JobStatus,
    summary="Get a job's status",
    description="Returns the lifecycle state of a verification or agent job, plus its result "
    "once it finishes. Agent jobs also carry a tail of the agent's transcript.",
)
async def job_get(job_id: str):
    """Return one job's status record."""
    record = queue.get(job_id)
    if record is None:
        return _error(404, f"no job '{job_id}'")
    live = agent_mod.ACTIVE_JOBS.get(job_id)
    if live is not None:
        # Read the transcript off disk so the panel can watch a session as it
        # works, rather than seeing nothing until the job ends.
        record["transcript"] = live.transcript()
        record["cancelled"] = live.cancelled
    return record


@verification_router.get(
    "/agent/jobs/{job_id}",
    response_model=JobStatus,
    summary="Get an agent job's status and transcript tail",
    description="Same record as `GET /verification/jobs/{job_id}`; kept as a separate path "
    "because the graph page polls it while an authoring job runs.",
)
async def agent_job_get(job_id: str):
    """Return one agent job's status record."""
    return await job_get(job_id)


@verification_router.post(
    "/jobs/{job_id}/cancel",
    summary="Stop a running agent session",
    description=(
        "Requires an ORCID login. Asks a running session to stop and kills its process group "
        "if it does not exit on its own. Whatever the agent already wrote to its outbox is "
        "still harvested and validated, so cancelling loses the session, not the finished work. "
        "404 if the job is unknown; 409 if it has already finished."
    ),
)
async def job_cancel_post(request: Request, job_id: str):
    """Stop a running agent session."""
    require_user(request)
    record = queue.get(job_id)
    if record is None:
        return _error(404, f"no job '{job_id}'")
    live = agent_mod.ACTIVE_JOBS.get(job_id)
    if live is None:
        return _error(409, f"job '{job_id}' is not running (state: {record.get('state')})")

    signalled = await asyncio.to_thread(live.cancel)
    queue.update(job_id, cancelled=True)
    return JSONResponse(content={"job_id": job_id, "cancelled": True, "signalled": signalled})


@verification_router.post(
    "/jobs/{job_id}/steer",
    summary="Send a live instruction to a running agent session",
    description=(
        "Requires an ORCID login. Body: `{\"message\": \"...\"}`. The instruction is queued and "
        "picked up at the session's next turn, then appears in the transcript. Steering guides "
        "the session; it does not widen what the agent may do - the tool policy and the outbox "
        "contract are unchanged. 404 if the job is unknown; 409 if it is not running."
    ),
)
async def job_steer_post(request: Request, job_id: str, body: SteerRequest):
    """Queue a live instruction for a running agent session."""
    require_user(request)
    record = queue.get(job_id)
    if record is None:
        return _error(404, f"no job '{job_id}'")
    live = agent_mod.ACTIVE_JOBS.get(job_id)
    if live is None:
        return _error(409, f"job '{job_id}' is not running (state: {record.get('state')})")

    try:
        await asyncio.to_thread(live.steer, body.message)
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(content={"job_id": job_id, "queued": True})


@verification_router.post(
    "/agent/jobs",
    response_model=JobStatus,
    summary="Ask the agent to author nodes for a claim",
    description=(
        "Requires an ORCID login, rate-limited per user. Body: "
        "`{\"request\": \"Verify that 30% of CA3 units respond to vis1\", \"root_node\": null}`. "
        "Spawns a sandboxed Claude Agent SDK session with the graph schema, dataset, "
        "node-authoring and "
        "recursive-verification skills and a read-only export of the manifest. The agent has no "
        "write access to the graph: it writes into an outbox, and on exit the server validates "
        "everything through the same path as `POST /verification/nodes` and inserts what passes "
        "as `proposed` nodes attributed to `<orcid> via agent job <id>`."
    ),
)
async def agent_job_post(request: Request, body: AgentJobRequest):
    """Queue a sandboxed agent job to author nodes for a claim."""
    user = require_user(request)
    text = (body.request or "").strip()
    if not text:
        return _error(400, "'request' is required")
    if len(text.encode("utf-8")) > agent_mod.MAX_REQUEST_BYTES:
        return _error(400, f"'request' exceeds {agent_mod.MAX_REQUEST_BYTES} bytes")

    allowed, message = agent_rate_limiter.check("verification-agent", user["orcid"])
    if not allowed:
        return _error(429, message)

    job_id = f"agent-{uuid.uuid4().hex[:12]}"
    record = await queue.submit(
        "agent",
        lambda: _run_agent_job(text, user["orcid"], job_id),
        job_id=job_id,
        orcid=user["orcid"],
    )
    return record


def _run_agent_job(text: str, orcid: str, job_id: str) -> dict:
    """Blocking body of an agent job: run sandboxed, then validate the outbox."""
    manifest = compile_manifest(store.list_nodes())
    job = agent_mod.AgentJob(job_id, text, manifest)
    agent_mod.ACTIVE_JOBS[job_id] = job
    try:
        sandbox_result = job.run()
        documents, code, rejected = agent_mod.read_outbox(job.dir)
        existing = store.nodes_by_id()
        accepted, more_rejected = agent_mod.validate_outbox(documents, existing)
        rejected.extend(more_rejected)

        accepted_ids: List[str] = []
        for doc in accepted:
            # Each node is stored independently: one that cannot be written
            # must not abort the loop and leave the rest of a validated batch
            # silently dropped. Code goes down first, so a failure part-way
            # leaves no node pointing at a half-written sidecar.
            try:
                agent_mod.attribute(doc, orcid, job.job_id)
                for relpath, data in (code.get(doc["id"]) or {}).items():
                    store.put_code_file(doc["id"], relpath, data)
                store.put_node(doc)
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                _logger.exception("agent outbox node %s could not be stored", doc.get("id"))
                rejected.append({"file": f"{doc.get('id')}.json", "reason": f"could not be stored: {exc}"})
                continue
            accepted_ids.append(doc["id"])

        if accepted_ids:
            store.recompile()

        return {
            "accepted": accepted_ids,
            "rejected": rejected,
            "transcript": job.transcript(),
            "cancelled": job.cancelled,
            "sandbox": {k: v for k, v in sandbox_result.items() if k != "output"},
        }
    finally:
        agent_mod.ACTIVE_JOBS.pop(job_id, None)
        job.cleanup()
