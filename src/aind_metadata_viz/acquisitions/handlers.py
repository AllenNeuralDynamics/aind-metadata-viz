"""FastAPI router for the scheduled-acquisitions REST endpoints.

See /docs (Swagger UI) for full request/response schemas.
"""

import logging
from typing import List

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .models import (
    ScheduledAcquisition,
    ScheduledAcquisitionCreate,
    ScheduledAcquisitionCreated,
    ScheduledAcquisitionDetail,
)
from .store import (
    add_scheduled_acquisition,
    get_scheduled_acquisition,
    get_scheduled_acquisitions,
)

_logger = logging.getLogger(__name__)

acquisitions_router = APIRouter(tags=["acquisitions"])


@acquisitions_router.post(
    "/scheduled-acquisitions",
    response_model=ScheduledAcquisitionCreated,
    summary="Schedule an acquisition",
    description=(
        "Validates `acquisition_type` against the configured allow-list (resolving `platform` "
        "automatically), stores the record, and returns a `uuid` that identifies it. 400 if "
        "`acquisition_type` isn't allowed."
    ),
)
async def scheduled_acquisitions_post(body: ScheduledAcquisitionCreate):
    try:
        acquisition_uuid = add_scheduled_acquisition(body.subject_id, body.date, body.acquisition_type)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        _logger.exception("POST /scheduled-acquisitions subject_id=%s", body.subject_id)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return ScheduledAcquisitionCreated(uuid=acquisition_uuid)


@acquisitions_router.get(
    "/scheduled-acquisitions",
    response_model=List[ScheduledAcquisition],
    summary="List scheduled acquisitions",
    description="Returns all scheduled acquisitions. By default only acquisitions scheduled for "
    "today or later are included; pass `include_past=true` to include past acquisitions too.",
)
async def scheduled_acquisitions_get(
    include_past: bool = Query(default=False, description="Include acquisitions scheduled before today"),
):
    try:
        records = get_scheduled_acquisitions(include_past=include_past)
    except Exception as e:
        _logger.exception("GET /scheduled-acquisitions include_past=%s", include_past)
        return JSONResponse(status_code=500, content={"error": str(e)})
    return records


@acquisitions_router.get(
    "/scheduled-acquisitions/{acquisition_uuid}",
    response_model=ScheduledAcquisitionDetail,
    summary="Get a scheduled acquisition by uuid",
    description="Returns the subject_id, date, platform, and acquisition_type for a single "
    "scheduled acquisition. 404 if the uuid isn't found.",
)
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

    return record
