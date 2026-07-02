"""S3-backed storage for allowed acquisition types and scheduled acquisitions.

Data is stored as JSON objects in S3 (bucket: ``aind-scratch-data``, prefix:
``aind-metadata-viz-data/``).

Object layout::

    aind-metadata-viz-data/allowed_acquisition_types.json
    aind-metadata-viz-data/scheduled_acquisitions.json

* ``add_acquisition_type`` appends a new (platform, acquisition_type) pair.
* ``get_allowed_types`` returns all allowed (platform, acquisition_type) pairs.
* ``add_scheduled_acquisition`` validates acquisition_type, generates a uuid,
  and stores the record.
* ``get_scheduled_acquisitions`` returns all scheduled acquisitions, optionally
  filtered to future-or-today only.
* ``get_scheduled_acquisition`` returns a single record by uuid.
"""

import json
import uuid
from datetime import date
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError

from .models import ALLOWED_PLATFORMS

_S3_BUCKET = "aind-scratch-data"
_S3_PREFIX = "aind-metadata-viz-data"

_ALLOWED_TYPES_KEY = f"{_S3_PREFIX}/allowed_acquisition_types.json"
_SCHEDULED_ACQUISITIONS_KEY = f"{_S3_PREFIX}/scheduled_acquisitions.json"


def _s3():
    return boto3.client("s3")


def _put_json(key: str, obj) -> None:
    _s3().put_object(
        Bucket=_S3_BUCKET,
        Key=key,
        Body=json.dumps(obj).encode(),
        ContentType="application/json",
    )


def _get_json(key: str):
    try:
        response = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
        return json.loads(response["Body"].read().decode())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def get_allowed_types() -> List[dict]:
    """Return all allowed (platform, acquisition_type) pairs."""
    return _get_json(_ALLOWED_TYPES_KEY) or []


def add_acquisition_type(platform: str, acquisition_type: str) -> dict:
    """Add a new allowed (platform, acquisition_type) pair.

    Raises ``ValueError`` if ``platform`` is set but not in ``ALLOWED_PLATFORMS``
    (only enforced once that list has been populated). Deduplicates on the
    exact (platform, acquisition_type) pair.
    """
    if ALLOWED_PLATFORMS and platform not in ALLOWED_PLATFORMS:
        raise ValueError(f"platform '{platform}' is not one of the allowed platforms: {ALLOWED_PLATFORMS}")

    entries = get_allowed_types()
    entry = {"platform": platform, "acquisition_type": acquisition_type}
    if entry not in entries:
        entries.append(entry)
        _put_json(_ALLOWED_TYPES_KEY, entries)
    return entry


def _find_platform_for_type(acquisition_type: str) -> Optional[str]:
    """Return the platform registered for ``acquisition_type``, or None if not found."""
    for entry in get_allowed_types():
        if entry["acquisition_type"] == acquisition_type:
            return entry["platform"]
    return None


def add_scheduled_acquisition(subject_id: str, acquisition_date: date, acquisition_type: str) -> str:
    """Validate ``acquisition_type`` against the allowed types and store a new scheduled acquisition.

    Returns the generated uuid for the new record. Raises ``ValueError`` if
    ``acquisition_type`` is not in the allowed types list.
    """
    platform = _find_platform_for_type(acquisition_type)
    if platform is None:
        raise ValueError(f"acquisition_type '{acquisition_type}' is not an allowed acquisition type")

    acquisition_uuid = str(uuid.uuid4())
    records = _get_json(_SCHEDULED_ACQUISITIONS_KEY) or {}
    records[acquisition_uuid] = {
        "subject_id": subject_id,
        "date": acquisition_date.isoformat() if isinstance(acquisition_date, date) else acquisition_date,
        "acquisition_type": acquisition_type,
        "platform": platform,
    }
    _put_json(_SCHEDULED_ACQUISITIONS_KEY, records)
    return acquisition_uuid


def get_scheduled_acquisitions(include_past: bool = False) -> List[dict]:
    """Return all scheduled acquisitions, each including its ``uuid``.

    If ``include_past`` is False (default), only acquisitions scheduled for
    today or later are returned.
    """
    records = _get_json(_SCHEDULED_ACQUISITIONS_KEY) or {}
    today = date.today()
    results = []
    for acquisition_uuid, record in records.items():
        if not include_past and date.fromisoformat(record["date"]) < today:
            continue
        results.append({"uuid": acquisition_uuid, **record})
    return results


def get_scheduled_acquisition(acquisition_uuid: str) -> Optional[dict]:
    """Return a single scheduled acquisition record by uuid, or None if not found."""
    records = _get_json(_SCHEDULED_ACQUISITIONS_KEY) or {}
    return records.get(acquisition_uuid)
