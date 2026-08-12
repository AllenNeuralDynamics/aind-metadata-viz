import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from aind_metadata_viz.endpoints import router
from aind_metadata_viz.contributions.handlers import contributions_router
from aind_metadata_viz.acquisitions.handlers import acquisitions_router
from aind_metadata_viz.pinpoint.handlers import pinpoint_router
from aind_metadata_viz.chat import chat_router, mount_mcp_server, summary_router
from aind_metadata_viz.auth import auth_router, SESSION_SECRET

_OPENAPI_TAGS = [
    {"name": "health", "description": "Service health checks."},
    {"name": "redirects", "description": "Convenience redirects to the data portal's web UI."},
    {"name": "gather", "description": "Gather and validate metadata for a subject."},
    {"name": "query", "description": "Query the metadata store, directly or via the LLM query builder."},
    {"name": "upgrade", "description": "Upgrade metadata to the latest schema version."},
    {"name": "chat", "description": "Natural-language querying of the metadata store."},
    {"name": "summary", "description": "Summarize a metadata asset."},
    {"name": "contributions", "description": "CRediT authorship contribution tracking."},
    {"name": "acquisitions", "description": "Allowed acquisition types and scheduled acquisitions."},
    {"name": "pinpoint", "description": "Per-ORCID encrypted storage for arbitrary Pinpoint JSON blobs."},
]

app = FastAPI(openapi_tags=_OPENAPI_TAGS)

# Frontends reach the authenticated endpoints through a same-origin reverse
# proxy (see the data portal's nginx and Pinpoint's Apache config), so CORS
# only has to stay permissive for the public, unauthenticated read endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Signed-cookie session, used to keep ORCID-authenticated users logged in.
# ``SESSION_COOKIE_DOMAIN`` (e.g. ``.allenneuraldynamics.org``) widens the
# cookie to the shared parent domain, which a frontend on another subdomain
# needs: the OAuth callback runs on ``PUBLIC_BASE_URL``'s host, so the login
# state and the session it sets must be readable from that frontend's host too.
_session_cookie_domain = os.environ.get("SESSION_COOKIE_DOMAIN", "").strip()
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=os.environ.get("SESSION_INSECURE", "").lower() not in ("1", "true"),
    domain=_session_cookie_domain or None,
)

app.include_router(router)
app.include_router(auth_router)
app.include_router(contributions_router)
app.include_router(acquisitions_router)
app.include_router(pinpoint_router)
app.include_router(chat_router)
app.include_router(summary_router)
mount_mcp_server(app)
