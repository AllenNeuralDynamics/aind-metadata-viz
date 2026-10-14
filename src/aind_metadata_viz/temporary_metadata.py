"""Container-local metadata previews, isolated from production records."""

import asyncio
import copy
import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

from biodata_cache import asset_basics
from biodata_query.query import retrieve_records
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["temporary metadata"])
MAX_BYTES = 5 * 1024 * 1024
STORE_PATH = os.environ.get("TEMPORARY_METADATA_PATH", "/tmp/aind-temporary-metadata.sqlite3")
logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _connect():
    db = sqlite3.connect(STORE_PATH, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS records (name TEXT PRIMARY KEY, expires_at TEXT, payload TEXT)")
    return db


def _real_name_exists(name):
    cached = asset_basics()
    if cached["name"].eq(name).any():
        return True
    return bool(retrieve_records({"name": name}, limit=1, force_backend="docdb", projection={"name": 1}).records)


def _create(payload, requested_name):
    full_record = "quality_control" in payload
    record = copy.deepcopy(payload) if full_record else {"quality_control": copy.deepcopy(payload)}
    if not isinstance(record["quality_control"], dict):
        raise HTTPException(422, "quality_control must be an object")
    supplied_name = record.get("name")
    if requested_name is not None and supplied_name is not None and requested_name != supplied_name:
        raise HTTPException(422, "Query name and metadata name must match")
    name = requested_name if requested_name is not None else supplied_name
    if name is None:
        name = f"qc-test-{uuid4()}"
    if not isinstance(name, str) or not name.strip() or len(name) > 512:
        raise HTTPException(422, "name must be a nonempty string of at most 512 characters")
    try:
        if _real_name_exists(name):
            raise HTTPException(409, "An asset with this name already exists")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Temporary metadata uniqueness check failed")
        raise HTTPException(503, "Could not check asset name uniqueness; retry later")

    record["name"] = name
    record.setdefault("location", "")
    record.setdefault("data_description", {"project_name": "Temporary QC preview", "subject_id": "temporary"})
    now = _now()
    expires_at = (now + timedelta(days=30)).isoformat()
    envelope = {"name": name, "temporary": True, "expires_at": expires_at, "metadata": record}
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM records WHERE expires_at <= ?", (now.isoformat(),))
        try:
            db.execute("INSERT INTO records VALUES (?, ?, ?)", (name, expires_at, json.dumps(envelope)))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "A temporary record with this name already exists")
    return {"name": name, "temporary": True, "expires_at": expires_at,
            "quality_control_url": "https://data.allenneuraldynamics.org/quality_control?" + urlencode({"name": name})}


@router.post(
    "/temporary-metadata", status_code=201, summary="Create a temporary, read-only QC preview",
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
        "schema": {"type": "object", "additionalProperties": True},
        "examples": {"qc": {"value": {"metrics": []}},
                     "metadata": {"value": {"name": "my-preview", "quality_control": {"metrics": []}}}},
    }}}},
)
async def create_temporary_metadata(request: Request, name: str | None = Query(default=None)):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "Metadata exceeds the 5 MiB limit")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "Expected a JSON object")
    if not isinstance(payload, dict) or not ("quality_control" in payload or "metrics" in payload
                                           or payload.get("object_type") == "Quality control"):
        raise HTTPException(422, "Expected metadata with quality_control, or a quality_control object with metrics")
    return await asyncio.to_thread(_create, payload, name)


def _get(name):
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM records WHERE expires_at <= ?", (_now().isoformat(),))
        row = db.execute("SELECT payload FROM records WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise HTTPException(404, "Temporary metadata record not found or expired")
    return json.loads(row[0])


@router.get("/temporary-metadata", summary="Read an unexpired temporary metadata record")
async def get_temporary_metadata(name: str = Query(min_length=1)):
    return JSONResponse(await asyncio.to_thread(_get, name), headers={"Cache-Control": "no-store"})
