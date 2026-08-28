"""Session helpers built on Starlette's signed-cookie session.

After a successful ORCID login the user's identity is stored in
``request.session["user"]`` as ``{"orcid", "name"}``. These helpers read that
back out and provide a FastAPI dependency for endpoints that require a login.

A request with no session cookie (any non-browser client: a CLI, a script, an
agent) falls back to an ``Authorization: Bearer <token>`` header, checked
against the personal-access-token store in ``tokens.py``. This is the only
difference between a browser call and a headless one - everything downstream
of ``get_current_user`` (``require_user``, ``require_admin``, and every
handler that calls them) sees the same ``{"orcid", "name", "is_admin"}`` shape
either way and does not need to know which path produced it.
"""

from typing import Optional

from fastapi import HTTPException, Request

from . import config, tokens

SESSION_USER_KEY = "user"
_BEARER_PREFIX = "Bearer "


def _user_from_session_cookie(request: Request) -> Optional[dict]:
    """Return the raw ``{"orcid", "name"}`` stored by the session cookie, or None."""
    try:
        return request.session.get(SESSION_USER_KEY)
    except (AssertionError, AttributeError):
        # SessionMiddleware not installed (e.g. in some test contexts).
        return None


def _user_from_bearer_token(request: Request) -> Optional[dict]:
    """Return ``{"orcid", "name"}`` from a valid ``Authorization: Bearer`` header, or None."""
    header = request.headers.get("authorization", "")
    if not header.startswith(_BEARER_PREFIX):
        return None
    raw_token = header.removeprefix(_BEARER_PREFIX).strip()
    if not raw_token:
        return None
    return tokens.resolve_token(raw_token)


def _finalize(user: Optional[dict]) -> Optional[dict]:
    """Return the public ``{"orcid", "name", "is_admin"}`` shape, or None."""
    if not user or not user.get("orcid"):
        return None
    return {
        "orcid": user["orcid"],
        "name": user.get("name"),
        "is_admin": config.is_admin(user["orcid"]),
    }


def get_current_user(request: Request) -> Optional[dict]:
    """Return the logged-in user ``{"orcid", "name", "is_admin"}`` or None.

    Checks the signed session cookie first (the browser path), then falls
    back to a bearer personal-access-token (the headless-client path).
    """
    user = _user_from_session_cookie(request)
    if not user or not user.get("orcid"):
        user = _user_from_bearer_token(request)
    return _finalize(user)


def get_browser_user(request: Request) -> Optional[dict]:
    """Return the logged-in user from the session cookie only - no bearer token.

    Used to gate personal-access-token management itself: minting or revoking
    a token should require the real ORCID login it stands in for, not another
    token of the same kind. Otherwise a leaked token could mint its own
    longer-lived replacement instead of just being revoked.
    """
    return _finalize(_user_from_session_cookie(request))


def set_current_user(request: Request, orcid: str, name: Optional[str]) -> None:
    """Store the authenticated user in the session."""
    request.session[SESSION_USER_KEY] = {"orcid": orcid, "name": name}


def clear_current_user(request: Request) -> None:
    """Remove the authenticated user from the session (logout)."""
    request.session.pop(SESSION_USER_KEY, None)


def require_user(request: Request) -> dict:
    """FastAPI dependency: return the current user or raise 401."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_browser_user(request: Request) -> dict:
    """FastAPI dependency: return the session-cookie user or raise 401.

    Unlike ``require_user``, a bearer token is not accepted here. Use this
    for endpoints that must not be reachable with a token alone, such as
    token management itself.
    """
    user = get_browser_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Browser login required")
    return user


def require_admin(request: Request) -> dict:
    """FastAPI dependency: return the current user or raise 401/403."""
    user = require_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
