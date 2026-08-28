"""Authentication: ORCID OpenID Connect login, sessions, and API tokens.

Public API
----------
    auth_router           FastAPI router for the /auth/* endpoints.
    get_current_user      Read the logged-in user from the session or a bearer token.
    require_user          FastAPI dependency requiring any logged-in user (cookie or token).
    require_browser_user  FastAPI dependency requiring a real browser session (no token).
    require_admin         FastAPI dependency requiring an admin user.
    is_admin               Check an ORCID iD against the admin allowlist.

A headless client (CLI, agent) that cannot run the browser ORCID redirect
authenticates with a personal access token instead of a session cookie - see
``tokens.py`` for how a token is minted (``POST /auth/tokens``, itself
requiring a real browser session) and validated.
"""

from .config import SESSION_SECRET, is_admin
from .handlers import auth_router
from .session import (
    clear_current_user,
    get_current_user,
    require_admin,
    require_browser_user,
    require_user,
    set_current_user,
)

__all__ = [
    "auth_router",
    "SESSION_SECRET",
    "is_admin",
    "get_current_user",
    "set_current_user",
    "clear_current_user",
    "require_user",
    "require_browser_user",
    "require_admin",
]
