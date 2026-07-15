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
from datetime import datetime, timedelta, timezone
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


def _list_latest_project_keys() -> list:
    """Return the newest version object key for every project.

    Lists all project sub-prefixes under ``contributions-app/`` (skipping the
    reserved ``_passwords/``, ``_tokens/`` and ``images/`` prefixes) and returns
    the most recent version key for each.
    """
    versions_prefix = f"{_S3_PREFIX}/"
    paginator = _s3().get_paginator("list_objects_v2")

    passwords_prefix = f"{_S3_PREFIX}/_passwords/"
    tokens_prefix = f"{_S3_PREFIX}/_tokens/"
    members_prefix = f"{_S3_PREFIX}/_members/"
    images_prefix = f"{_S3_PREFIX}/images/"
    latest_keys = []
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=versions_prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            proj_prefix = cp["Prefix"]
            if proj_prefix in (passwords_prefix, tokens_prefix, members_prefix, images_prefix):
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


_MAX_TOKEN_DAYS = 365
_MAX_MULTI_AUTHOR_DAYS = 7


def _token_key(project_name: str) -> str:
    return f"{_S3_PREFIX}/_tokens/{_safe_key(project_name)}.json"


def create_token(
    project_name: str,
    token_type: str,
    author_name: Optional[str] = None,
    expires_days: int = 365,
    store_dir=None,  # retained for API compatibility; ignored
) -> str:
    """Create a scoped token for *project_name*.

    Parameters
    ----------
    project_name:
        Name of the target project.
    token_type:
        ``"add_author"`` (one-time use), ``"edit_author"`` (scoped to
        *author_name*, reusable until expiry), ``"multi_author"``
        (reusable, lets multiple people each add themselves, capped at 7 days),
        or ``"self_add"`` (permanent invite token — never expires, disabled
        manually by an admin; used with the ORCID login / membership flow).
    author_name:
        Required for ``"edit_author"`` tokens.
    expires_days:
        Days until expiry from now; capped at ``_MAX_TOKEN_DAYS`` (365) for
        ``add_author``/``edit_author``, or ``_MAX_MULTI_AUTHOR_DAYS`` (7) for
        ``multi_author``.

    Returns
    -------
    str
        The UUID token the recipient presents in place of a password.
    """
    if token_type not in ("add_author", "edit_author", "multi_author", "self_add"):
        raise ValueError(
            "token_type must be 'add_author', 'edit_author', 'multi_author', "
            f"or 'self_add', got {token_type!r}"
        )
    if token_type == "edit_author" and not author_name:
        raise ValueError("author_name is required for edit_author tokens")

    # ``self_add`` invite tokens are permanent: they never expire and are only
    # revoked when an admin disables them (see ``disable_token``).
    if token_type == "self_add":
        expires_at = None
    else:
        max_days = _MAX_MULTI_AUTHOR_DAYS if token_type == "multi_author" else _MAX_TOKEN_DAYS
        days = min(max(1, expires_days), max_days)
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    token_id = uuid.uuid4().hex
    key = _token_key(project_name)
    existing = _get_json(key) or {"tokens": []}
    existing["tokens"].append({
        "token_id": token_id,
        "token_type": token_type,
        "author_name": author_name,
        "expires_at": expires_at,
        "used": False,
        "disabled": False,
    })
    _put_json(key, existing)
    return token_id


def lookup_token(
    project_name: str,
    token_id: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> Optional[dict]:
    """Return the token record if it is valid (exists, unexpired, unused).

    Returns ``None`` when the token is absent, expired, or already consumed.
    The returned dict contains ``token_id``, ``token_type``, ``author_name``,
    ``expires_at``, and ``used``.
    """
    key = _token_key(project_name)
    data = _get_json(key)
    if data is None:
        return None

    now = datetime.now(timezone.utc)
    for token in data.get("tokens", []):
        if token["token_id"] != token_id:
            continue
        if token.get("used") or token.get("disabled"):
            return None
        expires_at = token.get("expires_at")
        if expires_at is not None and now > datetime.fromisoformat(expires_at):
            return None
        return token
    return None


def consume_token(
    project_name: str,
    token_id: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> None:
    """Mark *token_id* as used so it cannot be reused (for add_author tokens)."""
    key = _token_key(project_name)
    data = _get_json(key)
    if data is None:
        return
    for token in data.get("tokens", []):
        if token["token_id"] == token_id:
            token["used"] = True
            break
    _put_json(key, data)


def find_active_token(
    project_name: str,
    token_type: str,
    author_name: Optional[str] = None,
    store_dir=None,  # retained for API compatibility; ignored
) -> Optional[dict]:
    """Return an existing valid token matching *token_type*/*author_name*, or None.

    A token is "active" when it is unexpired and (for one-time tokens) unused.
    The returned dict has the same shape as ``lookup_token``'s result.
    """
    key = _token_key(project_name)
    data = _get_json(key)
    if data is None:
        return None

    now = datetime.now(timezone.utc)
    for token in data.get("tokens", []):
        if token.get("used") or token.get("disabled"):
            continue
        if token.get("token_type") != token_type:
            continue
        if token.get("author_name") != author_name:
            continue
        expires_at = token.get("expires_at")
        if expires_at is None:
            # Permanent token (e.g. ``self_add``) — active until disabled.
            return token
        try:
            expires = datetime.fromisoformat(expires_at)
        except (KeyError, ValueError):
            continue
        if now > expires:
            continue
        return token
    return None


def disable_token(
    project_name: str,
    token_id: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> bool:
    """Mark *token_id* as disabled so it can no longer be used.

    Returns True if a matching token was found and disabled, False otherwise.
    Used by admins to revoke a permanent ``self_add`` invite link.
    """
    key = _token_key(project_name)
    data = _get_json(key)
    if data is None:
        return False
    found = False
    for token in data.get("tokens", []):
        if token["token_id"] == token_id:
            token["disabled"] = True
            found = True
            break
    if found:
        _put_json(key, data)
    return found


# ---------------------------------------------------------------------------
# Project membership (ORCID-based edit access)
#
# Stored at ``contributions-app/_members/{safe_project}.json`` as::
#
#     {"members": [{"orcid", "name", "granted_at", "granted_via"}, ...]}
#
# Membership records which authenticated ORCID iDs may edit a project. They are
# created when a user follows a valid invite link and logs in (see the
# ``/contributions/join`` endpoint) and are independent of the legacy
# password/token auth, which continues to work unchanged.
# ---------------------------------------------------------------------------


def _members_key(project_name: str) -> str:
    return f"{_S3_PREFIX}/_members/{_safe_key(project_name)}.json"


def list_members(
    project_name: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> list:
    """Return the list of member records for *project_name* (possibly empty)."""
    data = _get_json(_members_key(project_name))
    if data is None:
        return []
    return data.get("members", [])


def is_member(
    project_name: str,
    orcid: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> bool:
    """Return True if *orcid* is a member of *project_name*."""
    return any(m.get("orcid") == orcid for m in list_members(project_name))


def add_member(
    project_name: str,
    orcid: str,
    name: Optional[str] = None,
    granted_via: Optional[str] = None,
    store_dir=None,  # retained for API compatibility; ignored
) -> dict:
    """Grant *orcid* edit access to *project_name*. Idempotent.

    Returns the (new or existing) member record. If the member already exists,
    the stored ``name`` is refreshed when a newer one is supplied.
    """
    key = _members_key(project_name)
    data = _get_json(key) or {"members": []}
    for member in data["members"]:
        if member.get("orcid") == orcid:
            if name and member.get("name") != name:
                member["name"] = name
                _put_json(key, data)
            return member
    record = {
        "orcid": orcid,
        "name": name,
        "granted_at": datetime.now(timezone.utc).isoformat(),
        "granted_via": granted_via,
    }
    data["members"].append(record)
    _put_json(key, data)
    return record


def remove_member(
    project_name: str,
    orcid: str,
    store_dir=None,  # retained for API compatibility; ignored
) -> bool:
    """Revoke *orcid*'s access to *project_name*. Returns True if removed."""
    key = _members_key(project_name)
    data = _get_json(key)
    if data is None:
        return False
    before = len(data.get("members", []))
    data["members"] = [m for m in data.get("members", []) if m.get("orcid") != orcid]
    if len(data["members"]) == before:
        return False
    _put_json(key, data)
    return True
