"""FastAPI router for the scheduled-acquisitions REST endpoints.

Routes
------
POST /acquisition-types
    Body: {"platform": str, "acquisition_type": str}
    Adds a new allowed (platform, acquisition_type) pair.

GET /acquisition-types
    Returns all allowed (platform, acquisition_type) pairs.

POST /scheduled-acquisitions
    Body: {"subject_id": str, "date": "YYYY-MM-DD", "acquisition_type": str}
    Validates acquisition_type against the allowed types, stores the record,
    and returns {"uuid": "<uuid>"}.

GET /scheduled-acquisitions?include_past=false
    Returns all scheduled acquisitions. By default only acquisitions scheduled
    for today or later are returned; pass include_past=true to include all.

GET /scheduled-acquisitions/{acquisition_uuid}
    Returns {"subject_id", "date", "platform", "acquisition_type"} for a
    single scheduled acquisition.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .store import (
    add_acquisition_type,
    add_scheduled_acquisition,
    get_allowed_types,
    get_scheduled_acquisition,
    get_scheduled_acquisitions,
)

_logger = logging.getLogger(__name__)

acquisitions_router = APIRouter()


@acquisitions_router.post("/acquisition-types")
async def acquisition_types_post(request: Request):
    body = await request.json()
    platform = body.get("platform")
    acquisition_type = body.get("acquisition_type")
    if not platform or not acquisition_type:
        return JSONResponse(
            status_code=400,
            content={"error": "platform and acquisition_type are required"},
        )

    try:
        entry = add_acquisition_type(platform, acquisition_type)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        _logger.exception("POST /acquisition-types platform=%s acquisition_type=%s", platform, acquisition_type)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(content=entry)


@acquisitions_router.get("/acquisition-types")
async def acquisition_types_get():
    try:
        entries = get_allowed_types()
    except Exception as e:
        _logger.exception("GET /acquisition-types")
        return JSONResponse(status_code=500, content={"error": str(e)})
    return JSONResponse(content=entries)


@acquisitions_router.post("/scheduled-acquisitions")
async def scheduled_acquisitions_post(request: Request):
    body = await request.json()
    subject_id = body.get("subject_id")
    acquisition_date = body.get("date")
    acquisition_type = body.get("acquisition_type")
    if not subject_id or not acquisition_date or not acquisition_type:
        return JSONResponse(
            status_code=400,
            content={"error": "subject_id, date, and acquisition_type are required"},
        )

    try:
        acquisition_uuid = add_scheduled_acquisition(subject_id, acquisition_date, acquisition_type)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        _logger.exception("POST /scheduled-acquisitions subject_id=%s", subject_id)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(content={"uuid": acquisition_uuid})


@acquisitions_router.get("/scheduled-acquisitions")
async def scheduled_acquisitions_get(request: Request):
    include_past = request.query_params.get("include_past", "false").lower() == "true"
    try:
        records = get_scheduled_acquisitions(include_past=include_past)
    except Exception as e:
        _logger.exception("GET /scheduled-acquisitions include_past=%s", include_past)
        return JSONResponse(status_code=500, content={"error": str(e)})
    return JSONResponse(content=records)


@acquisitions_router.get("/scheduled-acquisitions/{acquisition_uuid}")
async def scheduled_acquisition_get(acquisition_uuid: str):
    try:
        record = get_scheduled_acquisition(acquisition_uuid)
    except Exception as e:
        _logger.exception("GET /scheduled-acquisitions/%s", acquisition_uuid)
        return JSONResponse(status_code=500, content={"error": str(e)})

    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"No scheduled acquisition found for uuid '{acquisition_uuid}'"},
        )

    return JSONResponse(content=record)
