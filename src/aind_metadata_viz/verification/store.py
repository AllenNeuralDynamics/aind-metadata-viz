"""S3-backed storage for the verification graph.

Everything lives under one prefix in the bucket the portal already owns::

    s3://aind-scratch-data/verification-graph/
      nodes/<node-id>.json        # one document per node (source of truth)
      history/<node-id>/<ts>.json # previous versions, written before overwrite
      code/<node-id>/...          # code sidecars (analysis.py, tests, lock)
      runs/<node-id>/<ts>/...     # logs + result JSON from verification runs
      snapshots/graph.json        # compiled whole-graph snapshot for the UI
      manifest.json               # id -> {kind, label, status, updated} index

Node documents are the source of truth; ``graph.json`` and ``manifest.json``
are derived and rewritten by ``recompile`` after every accepted write.

Follows the store pattern the rest of the portal uses: module-level ``_s3()``
boto3 client, ``_put_json``/``_get_json`` helpers, ``NoSuchKey`` -> ``None``.
All calls here are blocking; handlers wrap them in ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from .graph import compile_manifest, compile_snapshot, now_iso

_S3_BUCKET = "aind-scratch-data"
_S3_PREFIX = "verification-graph"

NODES_PREFIX = f"{_S3_PREFIX}/nodes"
HISTORY_PREFIX = f"{_S3_PREFIX}/history"
CODE_PREFIX = f"{_S3_PREFIX}/code"
RUNS_PREFIX = f"{_S3_PREFIX}/runs"
SNAPSHOT_KEY = f"{_S3_PREFIX}/snapshots/graph.json"
MANIFEST_KEY = f"{_S3_PREFIX}/manifest.json"

#: Node ids are used directly as S3 key components, so they are restricted to
#: characters that cannot escape the prefix or confuse a path join.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: Same, for paths inside a code sidecar: one or two path segments, no dots.
_CODE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")

MAX_CODE_FILE_BYTES = 1 * 1024 * 1024


class InvalidId(ValueError):
    """Raised when a node id or code path is not safe to use as an S3 key."""


def _s3():
    """Return a boto3 S3 client."""
    return boto3.client("s3")


def safe_id(node_id: str) -> str:
    """Return *node_id* if it is a safe S3 key component, else raise ``InvalidId``."""
    if not node_id or not _ID_RE.match(node_id):
        raise InvalidId(f"invalid node id '{node_id}'")
    return node_id


def safe_code_path(path: str) -> str:
    """Return *path* if it is a safe relative path inside a code sidecar."""
    if not path or ".." in path.split("/") or not _CODE_PATH_RE.match(path):
        raise InvalidId(f"invalid code path '{path}'")
    return path


def _put_json(key: str, obj) -> None:
    """Write *obj* to *key* as pretty-printed JSON."""
    _s3().put_object(
        Bucket=_S3_BUCKET,
        Key=key,
        Body=json.dumps(obj, indent=2, sort_keys=True).encode(),
        ContentType="application/json",
    )


def _get_json(key: str):
    """Read JSON from *key*, or return None when the object does not exist."""
    body = _get_bytes(key)
    return None if body is None else json.loads(body.decode())


def _put_bytes(key: str, data: bytes, content_type: str) -> None:
    """Write raw *data* to *key*."""
    _s3().put_object(Bucket=_S3_BUCKET, Key=key, Body=data, ContentType=content_type)


def _get_bytes(key: str) -> Optional[bytes]:
    """Read raw bytes from *key*, or return None when the object does not exist."""
    try:
        response = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
        return response["Body"].read()
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
            return None
        raise


def _list_keys(prefix: str) -> List[Tuple[str, int]]:
    """Return (key, size) for every object under *prefix*."""
    paginator = _s3().get_paginator("list_objects_v2")
    keys: List[Tuple[str, int]] = []
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append((obj["Key"], obj.get("Size", 0)))
    return keys


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


def node_key(node_id: str) -> str:
    """Return the S3 key holding *node_id*'s document."""
    return f"{NODES_PREFIX}/{safe_id(node_id)}.json"


def get_node(node_id: str) -> Optional[dict]:
    """Return the node document for *node_id*, or None if it does not exist."""
    return _get_json(node_key(node_id))


def list_nodes() -> List[dict]:
    """Return every node document in the graph."""
    nodes = []
    for key, _size in _list_keys(f"{NODES_PREFIX}/"):
        if not key.endswith(".json"):
            continue
        doc = _get_json(key)
        if doc:
            nodes.append(doc)
    return nodes


def nodes_by_id() -> Dict[str, dict]:
    """Return every node document, keyed by id."""
    return {n["id"]: n for n in list_nodes() if n.get("id")}


def put_node(doc: dict, archive_previous: bool = True) -> dict:
    """Write *doc*, archiving the previous version under ``history/`` first.

    Returns the document as written (with ``provenance.updated`` stamped).
    """
    node_id = safe_id(doc["id"])
    if archive_previous:
        previous = get_node(node_id)
        if previous is not None:
            stamp = (previous.get("provenance") or {}).get("updated") or now_iso()
            _put_json(f"{HISTORY_PREFIX}/{node_id}/{stamp}.json", previous)

    provenance = doc.setdefault("provenance", {})
    provenance.setdefault("created", now_iso())
    provenance["updated"] = now_iso()
    _put_json(node_key(node_id), doc)
    return doc


def get_history(node_id: str) -> List[dict]:
    """Return previous versions of *node_id*, newest first."""
    prefix = f"{HISTORY_PREFIX}/{safe_id(node_id)}/"
    versions = [_get_json(key) for key, _size in _list_keys(prefix)]
    versions = [v for v in versions if v]
    versions.sort(key=lambda v: (v.get("provenance") or {}).get("updated") or "", reverse=True)
    return versions


# --------------------------------------------------------------------------
# Code sidecars
# --------------------------------------------------------------------------


def code_key(node_id: str, path: str) -> str:
    """Return the S3 key for one file in *node_id*'s code sidecar."""
    return f"{CODE_PREFIX}/{safe_id(node_id)}/{safe_code_path(path)}"


def put_code_file(node_id: str, path: str, data: bytes) -> None:
    """Write one file into *node_id*'s code sidecar."""
    if len(data) > MAX_CODE_FILE_BYTES:
        raise ValueError(f"code file '{path}' is {len(data)} bytes; limit is {MAX_CODE_FILE_BYTES}")
    _put_bytes(code_key(node_id, path), data, "text/plain; charset=utf-8")


def get_code_file(node_id: str, path: str) -> Optional[bytes]:
    """Return one file from *node_id*'s code sidecar, or None if absent."""
    return _get_bytes(code_key(node_id, path))


def list_code_files(node_id: str) -> List[dict]:
    """Return ``[{'path', 'size'}, ...]`` for *node_id*'s code sidecar."""
    prefix = f"{CODE_PREFIX}/{safe_id(node_id)}/"
    files = [
        {"path": key[len(prefix):], "size": size}
        for key, size in _list_keys(prefix)
        if key != prefix
    ]
    files.sort(key=lambda f: f["path"])
    return files


def load_code_dir(node_id: str) -> Dict[str, bytes]:
    """Return *node_id*'s whole code sidecar as ``{relative path: bytes}``."""
    contents = {}
    for entry in list_code_files(node_id):
        data = get_code_file(node_id, entry["path"])
        if data is not None:
            contents[entry["path"]] = data
    return contents


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


def put_run(node_id: str, stamp: str, result: dict, log: str = "") -> str:
    """Store one verification run's result and log; return its S3 prefix."""
    prefix = f"{RUNS_PREFIX}/{safe_id(node_id)}/{safe_code_path(stamp)}"
    _put_json(f"{prefix}/result.json", result)
    _put_bytes(f"{prefix}/log.txt", log.encode("utf-8", "replace"), "text/plain; charset=utf-8")
    return prefix


def list_runs(node_id: str) -> List[dict]:
    """Return every recorded run for *node_id*, newest first."""
    prefix = f"{RUNS_PREFIX}/{safe_id(node_id)}/"
    runs = []
    for key, _size in _list_keys(prefix):
        if not key.endswith("/result.json"):
            continue
        result = _get_json(key)
        if result:
            result["log"] = key[: -len("/result.json")]
            runs.append(result)
    runs.sort(key=lambda r: r.get("ran_at") or "", reverse=True)
    return runs


def get_run_log(node_id: str, stamp: str) -> Optional[str]:
    """Return the text log of one run, or None if it is not stored."""
    data = _get_bytes(f"{RUNS_PREFIX}/{safe_id(node_id)}/{safe_code_path(stamp)}/log.txt")
    return None if data is None else data.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Derived documents
# --------------------------------------------------------------------------


def recompile(nodes: Optional[List[dict]] = None) -> dict:
    """Rebuild ``snapshots/graph.json`` and ``manifest.json`` from the nodes.

    Pass *nodes* to compile a set already in hand; otherwise every node
    document is read back from S3 first.
    """
    documents = list_nodes() if nodes is None else nodes
    snapshot = compile_snapshot(documents)
    _put_json(SNAPSHOT_KEY, snapshot)
    _put_json(MANIFEST_KEY, compile_manifest(documents))
    return snapshot


def get_snapshot(rebuild_if_missing: bool = True) -> dict:
    """Return the compiled snapshot, recompiling it if it has not been written."""
    snapshot = _get_json(SNAPSHOT_KEY)
    if snapshot is None and rebuild_if_missing:
        return recompile()
    return snapshot or {"generated": now_iso(), "nodes": [], "edges": []}


def get_manifest() -> List[dict]:
    """Return the compact id -> summary index."""
    manifest = _get_json(MANIFEST_KEY)
    if manifest is None:
        recompile()
        manifest = _get_json(MANIFEST_KEY)
    return manifest or []
