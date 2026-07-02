"""Pydantic models for scheduled-acquisition tracking."""

import datetime
from typing import List

from pydantic import BaseModel, Field

# Placeholder for the fixed list of allowed platform values.
# When empty, platform values are not restricted. Populate this list to
# start enforcing which platforms may be registered.
ALLOWED_PLATFORMS: List[str] = []


class AcquisitionTypeEntry(BaseModel):
    """A single (platform, acquisition_type) pair allowed for scheduling."""

    platform: str = Field(..., description="Platform this acquisition type belongs to")
    acquisition_type: str = Field(..., description="Descriptive acquisition type string")


class ScheduledAcquisitionCreate(BaseModel):
    """Request body for registering a new scheduled acquisition."""

    subject_id: str = Field(..., description="Subject ID for this acquisition")
    date: datetime.date = Field(..., description="Scheduled date of the acquisition")
    acquisition_type: str = Field(
        ..., description="Acquisition type; must already be registered via POST /acquisition-types"
    )


class ScheduledAcquisitionCreated(BaseModel):
    """Response returned after registering a new scheduled acquisition."""

    uuid: str = Field(..., description="Unique identifier for the newly-scheduled acquisition")


class ScheduledAcquisitionDetail(BaseModel):
    """A scheduled acquisition's details, without its uuid (the caller already has it)."""

    subject_id: str = Field(..., description="Subject ID for this acquisition")
    date: datetime.date = Field(..., description="Scheduled date of the acquisition")
    acquisition_type: str = Field(..., description="Acquisition type, checked against allowed types")
    platform: str = Field(..., description="Platform resolved from the acquisition_type")


class ScheduledAcquisition(ScheduledAcquisitionDetail):
    """A scheduled acquisition registered ahead of time, including its uuid."""

    uuid: str = Field(..., description="Unique identifier for this scheduled acquisition")
