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


class ScheduledAcquisition(BaseModel):
    """A scheduled acquisition registered ahead of time."""

    uuid: str = Field(..., description="Unique identifier for this scheduled acquisition")
    subject_id: str = Field(..., description="Subject ID for this acquisition")
    date: datetime.date = Field(..., description="Scheduled date of the acquisition")
    acquisition_type: str = Field(..., description="Acquisition type, checked against allowed types")
    platform: str = Field(..., description="Platform resolved from the acquisition_type")
