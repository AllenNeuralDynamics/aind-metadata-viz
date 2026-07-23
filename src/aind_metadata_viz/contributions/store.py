"""S3-backed storage for ProjectContributions.

Each project's versions are stored as JSON objects in S3
(bucket: ``aind-scratch-data``, prefix: ``contributions-app/``).

Object layout::

    contributions-app/{safe_project_id}/{timestamp}_{version_id}.json

* ``store_contributions`` uploads a new version object and returns its UUID.
* ``get_contributions`` returns the latest version or a specific one by UUID.
* ``list_project_commits`` returns the version history newest-first, derived
  from the version object keys without reading each object.
* ``get_contributions_by_doi`` finds the latest version of any project by DOI.

Built-in examples can be seeded via ``scripts/seed_contributions.py``.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Union

import boto3
from botocore.exceptions import ClientError

from .models import ProjectContributions
from .serializers import from_json as _from_json, load as _load, to_json as _to_json

_S3_BUCKET = "aind-scratch-data"
_S3_PREFIX = "contributions-app"


def _s3():
    return boto3.client("s3")


def _safe_key(project_name: str) -> str:
    return project_name.replace("/", "_").replace("\\", "_")


def _safe_filename(project_name: str) -> str:
    return _safe_key(project_name) + ".json"


def _version_prefix(project_name: str) -> str:
    return f"{_S3_PREFIX}/{_safe_key(project_name)}/"


def _put_json(key: str, obj: dict) -> None:
    _s3().put_object(
        Bucket=_S3_BUCKET,
        Key=key,
        Body=json.dumps(obj).encode(),
        ContentType="application/json",
    )


def _get_json(key: str) -> Optional[dict]:
    try:
        response = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
        return json.loads(response["Body"].read().decode())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _list_version_keys(project_name: str) -> list:
    """Return all version object keys for *project_name*, sorted ascending by key name."""
    prefix = _version_prefix(project_name)
    paginator = _s3().get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return sorted(keys)


def store_contributions(
    project_name: str,
    data: Union[str, dict, ProjectContributions],
    message: Optional[str] = None,
    store_dir=None,  # retained for API compatibility; ignored
) -> str:
    if isinstance(data, ProjectContributions):
        contributions = data
    else:
        contributions = _load(data)

    version_id = uuid.uuid4().hex
    ts = datetime.now(timezone.utc).isoformat()
    commit_message = message or f"Update contributions for {project_name}"
    key = f"{_version_prefix(project_name)}{ts}_{version_id}.json"
    _put_json(key, {
        "id": version_id,
        "project_id": project_name,
        "timestamp": ts,
        "message": commit_message,
        "data": _to_json(contributions),
    })
    return version_id


def list_project_commits(
    project_name: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> list:
    keys = _list_version_keys(project_name)
    if not keys:
        raise FileNotFoundError(f"No commits found for project '{project_name}'")

    commits = []
    for key in reversed(keys):  # newest first
        # The commit id and timestamp are both encoded in the key name
        # ({prefix}{ts}_{version_id}.json), so we can build the history
        # listing without reading each version object from S3.
        filename = key.rsplit("/", 1)[-1]
        if filename.endswith(".json"):
            filename = filename[: -len(".json")]
        ts, _, version_id = filename.rpartition("_")
        if not ts or not version_id:
            continue
        commits.append({
            "commit": version_id,
            "timestamp": ts,
        })
    return commits


def get_contributions(
    project_name: str,
    commit_hash: Optional[str] = None,
    store_dir=None,  # retained for API compatibility; ignored
) -> ProjectContributions:
    keys = _list_version_keys(project_name)
    if not keys:
        raise FileNotFoundError(f"Project '{project_name}' not found")

    if commit_hash is not None:
        for key in keys:
            obj = _get_json(key)
            if obj and obj.get("id") == commit_hash:
                return _from_json(obj["data"])
        raise FileNotFoundError(
            f"Project '{project_name}' not found at ref '{commit_hash}'"
        )

    # Latest version is the last key (keys are sorted ascending by ISO timestamp prefix)
    obj = _get_json(keys[-1])
    if obj is None:
        raise FileNotFoundError(f"Project '{project_name}' not found")
    return _from_json(obj["data"])


def get_author_image_key(author_name: str) -> Optional[str]:
    """Return the S3 key of the author's headshot image, or None if not found.

    Images are stored under ``contributions-app/images/<author_name>.<ext>``
    with any file extension.  The first key whose stem matches *author_name*
    exactly is returned.
    """
    prefix = f"{_S3_PREFIX}/images/{author_name}"
    paginator = _s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key: str = obj["Key"]
            filename = key[len(f"{_S3_PREFIX}/images/"):]
            dot = filename.find(".")
            stem = filename[:dot] if dot != -1 else filename
            if stem == author_name:
                return key
    return None


def _list_latest_project_keys() -> list:
    """Return the newest version object key for every project.

    Lists all project sub-prefixes under ``contributions-app/`` (skipping the
    reserved ``images/`` prefix) and returns the most recent version key for
    each.
    """
    versions_prefix = f"{_S3_PREFIX}/"
    paginator = _s3().get_paginator("list_objects_v2")

    images_prefix = f"{_S3_PREFIX}/images/"
    latest_keys = []
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=versions_prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            proj_prefix = cp["Prefix"]
            if proj_prefix == images_prefix:
                continue
            proj_keys = []
            for inner_page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=proj_prefix):
                for obj in inner_page.get("Contents", []):
                    proj_keys.append(obj["Key"])
            if proj_keys:
                latest_keys.append(sorted(proj_keys)[-1])
    return latest_keys


def list_all_projects(
    store_dir=None,  # retained for API compatibility; ignored
) -> list:
    """Return the sorted list of all current project names.

    Reads the latest version object of every project to recover the true
    ``project_id`` (the S3 prefix is a lossy ``_``-escaped form of the name).
    """
    names = set()
    for key in _list_latest_project_keys():
        obj = _get_json(key)
        if obj and obj.get("project_id"):
            names.add(obj["project_id"])
    return sorted(names)


def get_contributions_by_doi(
    doi: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> ProjectContributions:
    """Return the latest version of any project whose DOI matches *doi*.

    Raises ``FileNotFoundError`` when no matching project is found.
    """
    for key in _list_latest_project_keys():
        obj = _get_json(key)
        if obj:
            contrib = _from_json(obj["data"])
            if contrib.doi and doi in contrib.doi:
                return contrib

    raise FileNotFoundError(f"No project found with DOI '{doi}'")
