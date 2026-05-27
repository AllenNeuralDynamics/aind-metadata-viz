"""S3-backed storage for ProjectContributions.

Each project's versions are stored as JSON objects in S3
(bucket: ``aind-scratch-data``, prefix: ``contributions-app/``).

Object layout::

    contributions-app/{safe_project_id}/{timestamp}_{version_id}.json
    contributions-app/_passwords/{safe_project_id}.json

* ``store_contributions`` uploads a new version object and returns its UUID.
* ``get_contributions`` returns the latest version or a specific one by UUID.
* ``list_project_commits`` returns the version history newest-first.
* ``set_project_password`` protects a project with a PBKDF2-hashed password.
* ``verify_project_password`` checks a supplied password against the stored hash.
* ``get_contributions_by_doi`` finds the latest version of any project by DOI.

Built-in examples can be seeded via ``scripts/seed_contributions.py``.
"""

import base64
import hashlib
import hmac
import json
import os
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


def _password_key(project_name: str) -> str:
    return f"{_S3_PREFIX}/_passwords/{_safe_key(project_name)}.json"


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
        obj = _get_json(key)
        if obj:
            commits.append({
                "commit": obj["id"],
                "timestamp": obj["timestamp"],
                "message": obj["message"],
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


_PBKDF2_ITERATIONS = 200_000


def set_project_password(
    project_name: str,
    password: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> None:
    """Protect a project with a password.

    ``password`` should be a pre-hashed string supplied by the client (e.g.
    a SHA-256 hex digest of the raw password).  It is stretched with
    PBKDF2-HMAC-SHA-256 before being written to S3 so the stored value
    cannot be used directly to authenticate.
    """
    salt = os.urandom(32)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    _put_json(_password_key(project_name), {
        "salt": base64.b64encode(salt).decode(),
        "pw_hash": base64.b64encode(pw_hash).decode(),
    })


def verify_project_password(
    project_name: str,
    password: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> bool:
    """Return True if *password* matches the stored hash for *project_name*.

    Returns True unconditionally when no password has been set for the
    project (i.e. the project is publicly accessible).
    """
    obj = _get_json(_password_key(project_name))
    if obj is None:
        return True

    salt = base64.b64decode(obj["salt"])
    stored_hash = base64.b64decode(obj["pw_hash"])
    check_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(check_hash, stored_hash)


def is_project_locked(
    project_name: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> bool:
    """Return True if *project_name* has a password set, False otherwise."""
    return _get_json(_password_key(project_name)) is not None


def get_contributions_by_doi(
    doi: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> ProjectContributions:
    """Return the latest version of any project whose DOI matches *doi*.

    Raises ``FileNotFoundError`` when no matching project is found.
    """
    # List all project sub-prefixes under contributions-app/
    versions_prefix = f"{_S3_PREFIX}/"
    paginator = _s3().get_paginator("list_objects_v2")

    # Collect the latest key per project by listing with delimiter
    # Skip _passwords/ which is not a project prefix
    passwords_prefix = f"{_S3_PREFIX}/_passwords/"
    latest_keys = []
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=versions_prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            proj_prefix = cp["Prefix"]
            if proj_prefix == passwords_prefix:
                continue
            proj_keys = []
            for inner_page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=proj_prefix):
                for obj in inner_page.get("Contents", []):
                    proj_keys.append(obj["Key"])
            if proj_keys:
                latest_keys.append(sorted(proj_keys)[-1])

    for key in latest_keys:
        obj = _get_json(key)
        if obj:
            contrib = _from_json(obj["data"])
            if contrib.doi and doi in contrib.doi:
                return contrib

    raise FileNotFoundError(f"No project found with DOI '{doi}'")
