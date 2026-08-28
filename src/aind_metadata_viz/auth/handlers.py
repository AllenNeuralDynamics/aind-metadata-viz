"""FastAPI router for authentication (ORCID OpenID Connect) and API tokens.

Routes
------
GET    /auth/orcid/login    Redirect to ORCID to authenticate.
GET    /auth/orcid/callback  ORCID redirects back here; sets the session.
POST   /auth/logout          Clear the session.
GET    /auth/me              Return the current user, or 401 if not logged in.
POST   /auth/tokens           Mint a personal access token for the caller.
GET    /auth/tokens           List the caller's own tokens (never raw values).
DELETE /auth/tokens/{token_id} Revoke one of the caller's own tokens.

The token routes exist for headless clients (CLI tools, agents) that cannot
run the browser-based ORCID redirect: log in once here in a browser, mint a
token, then use ``Authorization: Bearer <token>`` for everything else. See
``tokens.py`` for what a token is and how it is stored.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import config, orcid, session, tokens
from .session import require_browser_user

_logger = logging.getLogger(__name__)

auth_router = APIRouter(tags=["auth"])


class TokenCreateRequest(BaseModel):
    """Body of ``POST /auth/tokens``."""

    label: str = Field(..., min_length=1, max_length=200, description="Human-readable name, e.g. 'laptop CLI'")
    ttl_days: int = Field(default=tokens.DEFAULT_TTL_DAYS, ge=1, le=tokens.MAX_TTL_DAYS)


# Session key holding the post-login redirect target.
_NEXT_KEY = "post_login_next"


@auth_router.get("/auth/orcid/login", summary="Begin ORCID login")
async def orcid_login(
    request: Request,
    next: str = Query(default="/", description="URL to return to after login"),
):
    # Stash the return URL in the session; Authlib manages the OAuth state.
    request.session[_NEXT_KEY] = next
    redirect_uri = config.orcid_redirect_uri()
    return await orcid.authorize_redirect(request, redirect_uri)


@auth_router.get("/auth/orcid/callback", summary="ORCID login callback")
async def orcid_callback(request: Request):
    try:
        user = await orcid.fetch_user(request)
    except Exception as e:  # pragma: no cover - network/validation failures
        _logger.exception("ORCID callback failed")
        return JSONResponse(status_code=400, content={"error": f"Login failed: {e}"})

    session.set_current_user(request, user["orcid"], user.get("name"))
    next_url = request.session.pop(_NEXT_KEY, "/") or "/"
    return RedirectResponse(url=next_url, status_code=303)


@auth_router.post("/auth/logout", summary="Log out")
async def logout(request: Request):
    session.clear_current_user(request)
    return JSONResponse(content={"ok": True})


@auth_router.get("/auth/me", summary="Current authenticated user")
async def me(request: Request):
    user = session.get_current_user(request)
    if user is None:
        return JSONResponse(status_code=401, content={"error": "Not logged in"})
    return JSONResponse(content=user)


@auth_router.post(
    "/auth/tokens",
    summary="Mint a personal access token",
    description=(
        "Creates a bearer token for headless clients (CLI tools, agents). The raw "
        "token is returned only in this response - store it now, it cannot be "
        "retrieved again, only revoked and replaced with a new one. Requires a "
        "real browser ORCID session; an existing token cannot be used to mint "
        "another."
    ),
)
async def create_token(request: Request, body: TokenCreateRequest):
    user = require_browser_user(request)
    created = tokens.create_token(user["orcid"], user.get("name"), body.label, body.ttl_days)
    return JSONResponse(status_code=201, content=created)


@auth_router.get(
    "/auth/tokens",
    summary="List my personal access tokens",
    description="Metadata only (id, label, timestamps) - never a raw or full token value.",
)
async def list_tokens(request: Request):
    user = require_browser_user(request)
    return JSONResponse(content=tokens.list_tokens(user["orcid"]))


@auth_router.delete(
    "/auth/tokens/{token_id}",
    summary="Revoke a personal access token",
)
async def revoke_token(request: Request, token_id: str):
    user = require_browser_user(request)
    if not tokens.revoke_token(user["orcid"], token_id):
        raise HTTPException(status_code=404, detail="No such token")
    return JSONResponse(content={"ok": True})
