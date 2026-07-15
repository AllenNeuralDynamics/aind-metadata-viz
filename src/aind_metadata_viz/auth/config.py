"""Configuration for the OAuth / OpenID Connect login flow.

All values are read from environment variables so secrets are never
committed. The ORCID app must be registered at https://orcid.org
(Developer Tools) with the redirect URI ``{PUBLIC_BASE_URL}/auth/orcid/callback``.

Environment variables
---------------------
ORCID_CLIENT_ID, ORCID_CLIENT_SECRET
    Credentials of the registered ORCID API client.
ORCID_ISSUER
    OIDC issuer base URL. Defaults to ``https://orcid.org``.
SESSION_SECRET
    Secret key used to sign the session cookie. Required in production.
ADMIN_ORCIDS
    Comma-separated ORCID iDs granted admin privileges.
PUBLIC_BASE_URL
    Public base URL of this service, used to build the OAuth redirect URI.
"""

import os
from functools import lru_cache


ORCID_CLIENT_ID = os.environ.get("ORCID_CLIENT_ID", "")
ORCID_CLIENT_SECRET = os.environ.get("ORCID_CLIENT_SECRET", "")
ORCID_ISSUER = os.environ.get("ORCID_ISSUER", "https://orcid.org").rstrip("/")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-session-secret")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


ORCID_METADATA_URL = f"{ORCID_ISSUER}/.well-known/openid-configuration"


@lru_cache(maxsize=1)
def admin_orcids() -> frozenset:
    """Return the set of ORCID iDs configured as admins."""
    raw = os.environ.get("ADMIN_ORCIDS", "")
    return frozenset(o.strip() for o in raw.split(",") if o.strip())


def is_admin(orcid: str) -> bool:
    """Return True if *orcid* is in the configured admin allowlist."""
    return bool(orcid) and orcid in admin_orcids()


def orcid_redirect_uri() -> str:
    """Return the OAuth redirect URI for the ORCID callback."""
    return f"{PUBLIC_BASE_URL}/auth/orcid/callback"
