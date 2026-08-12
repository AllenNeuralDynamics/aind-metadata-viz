"""FastAPI router for the Pinpoint per-account blob endpoints.

A blob holds an arbitrary file: a JSON document when posted as
``application/json``, otherwise opaque bytes tagged with the posted content
type and served back under it.

Both endpoints require an ORCID login (see ``/auth/orcid/login``); the blob
namespace is keyed off the logged-in user's ORCID iD, so a user can only ever
read or write their own data. See /docs (Swagger UI) for full schemas.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from ..auth import require_user
from .store import (
    DEFAULT_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    DecryptionError,
    get_file,
    list_blobs,
    store_file,
)

_logger = logging.getLogger(__name__)

pinpoint_router = APIRouter(tags=["pinpoint"])


@pinpoint_router.get(
    "/pinpoint-get",
    summary="Fetch one of the logged-in user's Pinpoint blobs",
    description=(
        "Requires an ORCID login (`/auth/orcid/login`). Returns the decrypted blob "
        "stored under `name` for the logged-in ORCID iD, served under the content type it "
        "was posted with. Omit `name` to list the caller's blobs instead "
        "(`[{\"name\", \"timestamp\", \"content_type\", \"key_source\"}, ...]`). If the blob was "
        "stored with a `password`, the same `password` must be supplied here; a missing or "
        "wrong password returns 401."
    ),
)
async def pinpoint_get(
    request: Request,
    name: Optional[str] = Query(default=None, description="Blob name; omit to list all blobs"),
    password: Optional[str] = Query(
        default=None, description="Required only if the blob was stored with a password"
    ),
):
    user = require_user(request)
    orcid = user["orcid"]

    if not name:
        try:
            entries = await asyncio.to_thread(list_blobs, orcid)
        except Exception as e:
            _logger.exception("GET /pinpoint-get list orcid=%s", orcid)
            return JSONResponse(status_code=500, content={"error": str(e)})
        return JSONResponse(content=entries)

    try:
        payload, content_type = await asyncio.to_thread(get_file, orcid, name, password)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except DecryptionError as e:
        return JSONResponse(status_code=401, content={"error": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        _logger.exception("GET /pinpoint-get orcid=%s name=%s", orcid, name)
        return JSONResponse(status_code=500, content={"error": str(e)})

    if content_type == JSON_CONTENT_TYPE:
        return JSONResponse(content=json.loads(payload.decode("utf-8")))
    return Response(content=payload, media_type=content_type)


@pinpoint_router.post(
    "/pinpoint-post",
    summary="Store one of the logged-in user's Pinpoint blobs",
    description=(
        "Requires an ORCID login (`/auth/orcid/login`). The request body is an arbitrary file - "
        "a JSON document when sent as `application/json`, otherwise opaque bytes tagged with "
        "the request's content type - stored encrypted under `name` for the logged-in ORCID iD "
        "and replacing any "
        "previous blob of that name. Blobs are always encrypted at rest with AES-256-GCM: by "
        "default the key is derived from the caller's ORCID iD plus a server secret. Supply "
        "`password` to derive the key from the ORCID iD plus that password instead, in which "
        "case the same `password` is required on `/pinpoint-get`."
    ),
)
async def pinpoint_post(
    request: Request,
    name: Optional[str] = Query(default=None, description="Blob name (required; 400 if missing)"),
    password: Optional[str] = Query(
        default=None, description="Optional password to encrypt the blob with"
    ),
):
    user = require_user(request)
    orcid = user["orcid"]

    if not name:
        return JSONResponse(
            status_code=400, content={"error": "name query parameter is required"}
        )

    body = await request.body()
    if not body:
        return JSONResponse(status_code=400, content={"error": "request body is required"})

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
    if not content_type:
        content_type = DEFAULT_CONTENT_TYPE

    # A JSON body is validated up front so a malformed document is rejected
    # rather than stored as opaque bytes; anything else is stored verbatim.
    if content_type == JSON_CONTENT_TYPE:
        try:
            json.loads(body.decode("utf-8"))
        except Exception as e:
            return JSONResponse(
                status_code=400, content={"error": f"Failed to parse body: {e}"}
            )

    try:
        meta = await asyncio.to_thread(
            store_file, orcid, name, body, content_type, password
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        _logger.exception("POST /pinpoint-post orcid=%s name=%s", orcid, name)
        return JSONResponse(status_code=500, content={"error": str(e)})
    return JSONResponse(content=meta)
