"""acquisitions — allowed acquisition types and scheduled acquisitions.

Public API
----------
Models:
    AcquisitionTypeEntry, ScheduledAcquisition, ALLOWED_PLATFORMS

Storage (S3-backed):
    add_acquisition_type, get_allowed_types,
    add_scheduled_acquisition, get_scheduled_acquisitions, get_scheduled_acquisition
"""

from .models import ALLOWED_PLATFORMS, AcquisitionTypeEntry, ScheduledAcquisition
from .store import (
    add_acquisition_type,
    add_scheduled_acquisition,
    get_allowed_types,
    get_scheduled_acquisition,
    get_scheduled_acquisitions,
)

__all__ = [
    "ALLOWED_PLATFORMS",
    "AcquisitionTypeEntry",
    "ScheduledAcquisition",
    "add_acquisition_type",
    "get_allowed_types",
    "add_scheduled_acquisition",
    "get_scheduled_acquisitions",
    "get_scheduled_acquisition",
]
