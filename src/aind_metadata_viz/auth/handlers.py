"""FastAPI router for authentication (ORCID OpenID Connect).

Routes
------
GET  /auth/orcid/login    Redirect to ORCID to authenticate.
GET  /auth/orcid/callback  ORCID redirects back here; sets the session.
POST /auth/logout          Clear the session.
GET  /auth/me              Return the current user, or 401 if not logged in.
"""

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import config, orcid, session

_logger = logging.getLogger(__name__)

auth_router = APIRouter(tags=["auth"])

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
