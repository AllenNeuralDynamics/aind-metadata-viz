"""S3-backed encrypted storage for arbitrary Pinpoint files.

A blob's payload is an arbitrary byte string tagged with a content type, so a
blob can hold a JSON document (``store_blob``/``get_blob``) or any binary file
such as an experiment zip (``store_file``/``get_file``).

Each blob belongs to exactly one ORCID account and is stored as a single JSON
object in S3 (bucket: ``aind-scratch-data``, prefix ``pinpoint/accounts/``)::

    pinpoint/accounts/{orcid}/{safe_name}.json

The payload is never stored in the clear. The envelope written to S3 is::

    {
      "name": "<blob name>",
      "orcid": "<owner ORCID iD>",
      "timestamp": "<ISO-8601 UTC>",
      "content_type": "<MIME type of the payload>",
      "cipher": "aes-256-gcm",
      "kdf": "pbkdf2-sha256",
      "iterations": 200000,
      "key_source": "server" | "password",
      "salt": "<base64>",
      "nonce": "<base64>",
      "ciphertext": "<base64>"
    }

Key derivation
--------------
An ORCID iD is public information, so it cannot on its own be a secret. The
key is therefore always derived from the owner's ORCID iD *plus* a second
secret:

* ``key_source="server"`` (default) — the second secret is the server-side
  ``PINPOINT_ENCRYPTION_SECRET`` (falling back to ``SESSION_SECRET``). This
  protects blobs against anyone who can read the S3 bucket but does not know
  the server secret.
* ``key_source="password"`` — the second secret is a ``password`` supplied by
  the client on POST. The same password must be supplied on GET; the server
  cannot recover the blob without it. Use this for data that must stay
  readable only to the owner, even from the server operator's perspective.

The ORCID iD and the blob name are bound into the AES-GCM additional
authenticated data, so a blob cannot be replayed under another account or
another name.
"""

import base64
import json
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import quote, unquote

import boto3
from botocore.exceptions import ClientError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_S3_BUCKET = "aind-scratch-data"
_S3_PREFIX = "pinpoint/accounts"

_CIPHER = "aes-256-gcm"
_KDF = "pbkdf2-sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16
_NONCE_BYTES = 12

MAX_BLOB_BYTES = 250 * 1024 * 1024

JSON_CONTENT_TYPE = "application/json"
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# Envelope fields `list_blobs` reports, mirrored into S3 object metadata.
_LISTING_FIELDS = ("name", "timestamp", "content_type", "key_source")


class DecryptionError(Exception):
    """Raised when a blob cannot be decrypted with the supplied credentials."""


def _s3():
    return boto3.client("s3")


def _server_secret() -> str:
    secret = os.environ.get("PINPOINT_ENCRYPTION_SECRET")
    if secret:
        return secret
    from ..auth import config

    return config.SESSION_SECRET


def _safe_component(value: str) -> str:
    cleaned = "".join(
        c if (c.isalnum() or c in "-_.") else "_" for c in (value or "").strip()
    )
    cleaned = cleaned.strip("._")
    if not cleaned:
        raise ValueError("name must contain at least one alphanumeric character")
    return cleaned[:128]


def _account_prefix(orcid: str) -> str:
    return f"{_S3_PREFIX}/{_safe_component(orcid)}/"


def _blob_key(orcid: str, name: str) -> str:
    return f"{_account_prefix(orcid)}{_safe_component(name)}.json"


def _derive_key(orcid: str, password: Optional[str], salt: bytes) -> bytes:
    material = f"{orcid}\x00{password if password else _server_secret()}"
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return kdf.derive(material.encode("utf-8"))


def _aad(orcid: str, name: str) -> bytes:
    return f"{orcid}\x00{_safe_component(name)}".encode("utf-8")


def _put_json(key: str, obj: dict, listing_metadata: dict) -> None:
    # The listing fields are duplicated into S3 object metadata so `list_blobs`
    # can read them with `head_object` instead of downloading whole envelopes,
    # which may be hundreds of megabytes each.
    _s3().put_object(
        Bucket=_S3_BUCKET,
        Key=key,
        Body=json.dumps(obj).encode(),
        ContentType="application/json",
        Metadata={k: quote(str(v)) for k, v in listing_metadata.items()},
    )


def _get_json(key: str) -> Optional[dict]:
    try:
        response = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
        return json.loads(response["Body"].read().decode())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def store_file(
    orcid: str,
    name: str,
    payload: bytes,
    content_type: str = DEFAULT_CONTENT_TYPE,
    password: Optional[str] = None,
) -> dict:
    """Encrypt and store the bytes *payload* as the blob *name* owned by *orcid*.

    *content_type* is recorded alongside the blob and returned by ``get_file``.
    Returns the stored metadata (without the ciphertext).
    """
    if not orcid:
        raise ValueError("orcid is required")
    plaintext = payload
    if len(plaintext) > MAX_BLOB_BYTES:
        raise ValueError(
            f"blob is {len(plaintext)} bytes; limit is {MAX_BLOB_BYTES} bytes"
        )

    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    key = _derive_key(orcid, password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _aad(orcid, name))

    envelope = {
        "name": name,
        "orcid": orcid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content_type": content_type or DEFAULT_CONTENT_TYPE,
        "cipher": _CIPHER,
        "kdf": _KDF,
        "iterations": _ITERATIONS,
        "key_source": "password" if password else "server",
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
    _put_json(
        _blob_key(orcid, name),
        envelope,
        {field: envelope[field] for field in _LISTING_FIELDS},
    )
    return {k: v for k, v in envelope.items() if k not in ("ciphertext", "salt", "nonce")}


def store_blob(
    orcid: str,
    name: str,
    data,
    password: Optional[str] = None,
) -> dict:
    """Encrypt and store the JSON document *data* as the blob *name* owned by *orcid*.

    Returns the stored metadata (without the ciphertext).
    """
    return store_file(
        orcid,
        name,
        json.dumps(data, separators=(",", ":")).encode("utf-8"),
        JSON_CONTENT_TYPE,
        password,
    )


def get_file(
    orcid: str, name: str, password: Optional[str] = None
) -> Tuple[bytes, str]:
    """Return the decrypted payload and content type of the blob *name* owned by *orcid*.

    Raises ``FileNotFoundError`` if the blob does not exist and
    ``DecryptionError`` if the supplied credentials are wrong.
    """
    if not orcid:
        raise ValueError("orcid is required")
    envelope = _get_json(_blob_key(orcid, name))
    if envelope is None:
        raise FileNotFoundError(f"No blob named '{name}' for ORCID {orcid}")

    if envelope.get("key_source") == "password" and not password:
        raise DecryptionError(
            f"Blob '{name}' was stored with a password; supply the same password to read it"
        )

    salt = base64.b64decode(envelope["salt"])
    nonce = base64.b64decode(envelope["nonce"])
    ciphertext = base64.b64decode(envelope["ciphertext"])
    key = _derive_key(orcid, password, salt)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _aad(orcid, name))
    except InvalidTag:
        raise DecryptionError(f"Failed to decrypt blob '{name}': wrong password") from None
    return plaintext, envelope.get("content_type") or DEFAULT_CONTENT_TYPE


def get_blob(orcid: str, name: str, password: Optional[str] = None):
    """Return the decrypted JSON payload of the blob *name* owned by *orcid*.

    Raises ``FileNotFoundError`` if the blob does not exist, ``DecryptionError``
    if the supplied credentials are wrong, and ``ValueError`` if the blob does
    not hold JSON.
    """
    payload, content_type = get_file(orcid, name, password)
    if content_type != JSON_CONTENT_TYPE:
        raise ValueError(f"Blob '{name}' holds {content_type}, not JSON")
    return json.loads(payload.decode("utf-8"))


def list_blobs(orcid: str) -> List[dict]:
    """Return metadata for every blob owned by *orcid*, sorted by name."""
    if not orcid:
        raise ValueError("orcid is required")
    prefix = _account_prefix(orcid)
    paginator = _s3().get_paginator("list_objects_v2")
    entries = []
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            metadata = _head_metadata(key)
            if metadata is None:
                continue
            entries.append(
                {
                    "name": metadata.get("name") or key[len(prefix): -len(".json")],
                    "timestamp": metadata.get("timestamp"),
                    "content_type": metadata.get("content_type")
                    or DEFAULT_CONTENT_TYPE,
                    "key_source": metadata.get("key_source"),
                }
            )
    return sorted(entries, key=lambda e: e["name"])


def _head_metadata(key: str) -> Optional[dict]:
    """Return a blob's listing metadata from S3 object metadata, or None if it is gone."""
    try:
        response = _s3().head_object(Bucket=_S3_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    return {k: unquote(v) for k, v in (response.get("Metadata") or {}).items()}


