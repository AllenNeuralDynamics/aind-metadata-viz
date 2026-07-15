"""Session helpers built on Starlette's signed-cookie session.

After a successful ORCID login the user's identity is stored in
``request.session["user"]`` as ``{"orcid", "name"}``. These helpers read that
back out and provide a FastAPI dependency for endpoints that require a login.
"""

from typing import Optional

from fastapi import HTTPException, Request

from . import config

SESSION_USER_KEY = "user"


def get_current_user(request: Request) -> Optional[dict]:
    """Return the logged-in user ``{"orcid", "name", "is_admin"}`` or None."""
    try:
        user = request.session.get(SESSION_USER_KEY)
    except (AssertionError, AttributeError):
        # SessionMiddleware not installed (e.g. in some test contexts).
        return None
    if not user or not user.get("orcid"):
        return None
    return {
        "orcid": user["orcid"],
        "name": user.get("name"),
        "is_admin": config.is_admin(user["orcid"]),
    }


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


def require_admin(request: Request) -> dict:
    """FastAPI dependency: return the current user or raise 401/403."""
    user = require_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
