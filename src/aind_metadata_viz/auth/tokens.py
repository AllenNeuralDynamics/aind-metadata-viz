"""Personal access tokens for headless clients (CLI agents, scripts).

The ORCID login in ``orcid.py``/``handlers.py`` is a browser flow: it needs a
redirect, a callback, and a place to keep a signed session cookie. That is
fine for the data portal's own frontend, but it is unusable for an agent
running on someone's laptop with no browser session of its own - the only
workaround has been copying the session cookie out of the browser's dev
tools, which is fiddly and stops working the moment the cookie expires or
the user logs out.

A personal access token (PAT) is a long-lived, revocable credential a
*logged-in* user mints once from the browser (``POST /auth/tokens``) and then
hands to a headless client, which authenticates every request with
``Authorization: Bearer <token>`` instead of a cookie. This still requires
one real ORCID login (minting the token) - it removes the *cookie*, not the
identity check - but that login happens once, not every time a session
expires.

Only a SHA-256 hash of the token is ever stored, exactly like a GitHub PAT or
an npm auth token: this module cannot answer "what is token X's value", only
"does this candidate value hash to a token I have on record, and is it still
valid". The raw token is returned to the caller exactly once, at creation.

Storage
-------
One manifest object, following the same pattern as ``verification/store.py``::

    s3://aind-scratch-data/auth-tokens/manifest.json
        {"<sha256 hex>": {orcid, name, label, created_at, expires_at,
                           last_used_at, revoked}, ...}

The manifest is read-modify-written on every mutation (create/revoke), so two
concurrent mutations can race and one can clobber the other - the same
tradeoff ``verification/store.py`` already accepts for its own manifest.
Token volume here (per-person, occasional) makes that an acceptable risk
rather than one worth a conditional-PUT dance.

A short in-process cache avoids re-fetching the manifest from S3 on every
single authenticated request; ``last_used_at`` is likewise only persisted at
most once an hour per token, so normal traffic does not turn into a stream of
S3 writes.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

_S3_BUCKET = "aind-scratch-data"
_MANIFEST_KEY = "auth-tokens/manifest.json"

#: Prefix on every issued token so a leaked value is greppable/recognizable,
#: the same idea as GitHub's ``ghp_`` or OpenAI's ``sk-``.
TOKEN_PREFIX = "aindv_"

DEFAULT_TTL_DAYS = 180
MAX_TTL_DAYS = 365

#: How long a manifest read is trusted before re-fetching from S3.
_CACHE_TTL_SECONDS = 15
#: Minimum gap between persisted last_used_at updates for the same token.
_LAST_USED_WRITE_INTERVAL_SECONDS = 60 * 60

_cache: Dict[str, dict] = {}
_cache_loaded_at: float = 0.0


def _s3():
    """Return a boto3 S3 client."""
    return boto3.client("s3")


def _put_manifest(manifest: Dict[str, dict]) -> None:
    """Write *manifest* to S3 and refresh the in-process cache."""
    global _cache, _cache_loaded_at
    _s3().put_object(
        Bucket=_S3_BUCKET,
        Key=_MANIFEST_KEY,
        Body=json.dumps(manifest, indent=2, sort_keys=True).encode(),
        ContentType="application/json",
    )
    _cache = manifest
    _cache_loaded_at = time.time()


def _load_manifest(force: bool = False) -> Dict[str, dict]:
    """Return the token manifest, using the in-process cache when fresh."""
    global _cache, _cache_loaded_at
    if not force and _cache and (time.time() - _cache_loaded_at) < _CACHE_TTL_SECONDS:
        return _cache
    try:
        response = _s3().get_object(Bucket=_S3_BUCKET, Key=_MANIFEST_KEY)
        manifest = json.loads(response["Body"].read().decode())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
            manifest = {}
        else:
            raise
    _cache = manifest
    _cache_loaded_at = time.time()
    return manifest


def _now() -> datetime:
    """Return the current UTC time (its own function so tests can patch it)."""
    return datetime.now(timezone.utc)


def _hash(raw_token: str) -> str:
    """Return the SHA-256 hex digest of *raw_token*."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_token(orcid: str, name: Optional[str], label: str, ttl_days: int = DEFAULT_TTL_DAYS) -> dict:
    """Mint a new token for *orcid* and return it, raw value included.

    The raw token is present in the returned dict only this once; from here
    on only its hash is stored, so it cannot be recovered later, only revoked.
    """
    ttl_days = max(1, min(ttl_days, MAX_TTL_DAYS))
    raw_token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    digest = _hash(raw_token)
    created_at = _now()
    expires_at = created_at + timedelta(days=ttl_days)

    manifest = _load_manifest(force=True)
    manifest[digest] = {
        "orcid": orcid,
        "name": name,
        "label": label,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "last_used_at": None,
        "revoked": False,
    }
    _put_manifest(manifest)

    return {
        "id": digest[:8],
        "token": raw_token,
        "label": label,
        "created_at": manifest[digest]["created_at"],
        "expires_at": manifest[digest]["expires_at"],
    }


def list_tokens(orcid: str) -> List[dict]:
    """Return metadata (never the raw value or full hash) for *orcid*'s tokens."""
    manifest = _load_manifest()
    return [
        {
            "id": digest[:8],
            "label": entry["label"],
            "created_at": entry["created_at"],
            "expires_at": entry["expires_at"],
            "last_used_at": entry["last_used_at"],
            "revoked": entry["revoked"],
        }
        for digest, entry in sorted(manifest.items(), key=lambda kv: kv[1]["created_at"], reverse=True)
        if entry["orcid"] == orcid
    ]


def revoke_token(orcid: str, token_id: str) -> bool:
    """Revoke *orcid*'s token whose id (hash prefix) is *token_id*.

    Returns False if no such token exists for this ORCID - deliberately the
    same outcome whether the id is unknown or belongs to someone else, so a
    caller cannot use this to probe which ids exist.
    """
    manifest = _load_manifest(force=True)
    for digest, entry in manifest.items():
        if digest.startswith(token_id) and entry["orcid"] == orcid:
            if entry["revoked"]:
                return True
            entry["revoked"] = True
            _put_manifest(manifest)
            return True
    return False


def resolve_token(raw_token: str) -> Optional[dict]:
    """Return ``{"orcid", "name"}`` for a valid, unexpired, unrevoked token.

    Returns None for anything else (unknown, revoked, or expired), without
    distinguishing which - a bearer token is either good right now or it
    isn't. Updates ``last_used_at`` opportunistically, throttled so a busy
    client does not turn into a write on every single request.
    """
    if not raw_token.startswith(TOKEN_PREFIX):
        return None
    digest = _hash(raw_token)
    manifest = _load_manifest()
    entry = manifest.get(digest)
    if entry is None or entry["revoked"]:
        return None
    if datetime.fromisoformat(entry["expires_at"]) <= _now():
        return None

    last_used = entry.get("last_used_at")
    stale = last_used is None or (_now() - datetime.fromisoformat(last_used)).total_seconds() > (
        _LAST_USED_WRITE_INTERVAL_SECONDS
    )
    if stale:
        manifest = _load_manifest(force=True)
        fresh_entry = manifest.get(digest)
        if fresh_entry is not None and not fresh_entry["revoked"]:
            fresh_entry["last_used_at"] = _now().isoformat()
            _put_manifest(manifest)

    return {"orcid": entry["orcid"], "name": entry.get("name")}
