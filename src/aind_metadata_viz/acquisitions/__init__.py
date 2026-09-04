"""acquisitions — scheduled acquisitions and their internal allow-list.

Public API
----------
Models:
    AcquisitionTypeEntry, ScheduledAcquisition, ALLOWED_PLATFORMS

Storage (S3-backed):
    add_acquisition_type, get_allowed_types,
    add_scheduled_acquisition, get_scheduled_acquisitions, get_scheduled_acquisition

The acquisition-type allow-list is used internally when validating scheduled
acquisitions; its REST endpoints are not exposed by the application.
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
