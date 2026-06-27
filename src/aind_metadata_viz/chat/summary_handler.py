"""GET /summary endpoint: LLM summary of a single DocDB v2 record.

Hits the v2 metadata DB via ``biodata_query.retrieve_records`` (which
defaults to ``DOCDB_API_VERSION=v2``), shrinks the record so it fits in
the model's context window, and asks Bedrock for a high-level summary.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from biodata_query.query import retrieve_records
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .ratelimit import RateLimiter, client_ip
from .security import origin_error
from .summary import (
    DEFAULT_MAX_RECORD_BYTES,
    result_to_dict,
    summarize_record,
)

logger = logging.getLogger(__name__)

summary_rate_limiter = RateLimiter(
    per_minute=int(os.environ.get("SUMMARY_RATE_PER_MIN", "60")),
    per_day=int(os.environ.get("SUMMARY_RATE_PER_DAY", "200")),
    burst=int(os.environ.get("SUMMARY_RATE_BURST", "1")),
)

summary_router = APIRouter()


def _fetch_v2_record(name: str) -> Optional[dict]:
    """Fetch a single record from DocDB v2 by exact name match.

    ``force_backend='docdb'`` skips the cache so we always get the full
    record (the cache only stores a subset of fields).
    """
    result = retrieve_records(
        {"name": name}, limit=1, force_backend="docdb"
    )
    if not result.records:
        return None
    return result.records[0]


@summary_router.get("/summary")
async def summary_endpoint(
    request: Request,
    name: str = Query(..., description="Exact DocDB asset name"),
    id: Optional[str] = Query(
        default=None, description="Optional caller identifier"
    ),
):
    ip = client_ip(
        request.headers, request.client.host if request.client else None
    )
    blocked = origin_error(request.headers)
    if blocked:
        return JSONResponse(status_code=403, content={"error": blocked})

    allowed, error = summary_rate_limiter.check("summary", ip)
    if not allowed:
        return JSONResponse(status_code=429, content={"error": error})

    if not name or not name.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "'name' query parameter is required."},
        )

    try:
        record = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _fetch_v2_record(name)
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("DocDB lookup failed for name=%s", name)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to fetch record from DocDB v2.",
                "details": str(exc),
            },
        )

    if record is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": (
                    f"Asset '{name}' was not found in the DocDB v2 database."
                )
            },
        )

    try:
        result = await summarize_record(
            record, max_bytes=DEFAULT_MAX_RECORD_BYTES
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Summarization failed for name=%s", name)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Summarization failed.",
                "details": str(exc),
            },
        )

    logger.info(
        "summary ip=%s name=%s original=%d compacted=%d",
        ip,
        name,
        result.original_bytes,
        result.compacted_bytes,
    )
    _ = id  # accepted for parity with /chat but currently unused
    return JSONResponse(content=result_to_dict(result))
