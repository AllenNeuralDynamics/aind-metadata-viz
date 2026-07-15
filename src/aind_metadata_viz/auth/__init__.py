"""Authentication: ORCID OpenID Connect login and session management.

Public API
----------
    auth_router          FastAPI router for the /auth/* endpoints.
    get_current_user     Read the logged-in user from the session.
    require_user         FastAPI dependency requiring any logged-in user.
    require_admin        FastAPI dependency requiring an admin user.
    is_admin             Check an ORCID iD against the admin allowlist.
"""

from .config import SESSION_SECRET, is_admin
from .handlers import auth_router
from .session import (
    clear_current_user,
    get_current_user,
    require_admin,
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
    "require_admin",
]
