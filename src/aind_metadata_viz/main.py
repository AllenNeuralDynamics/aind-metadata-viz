import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from aind_metadata_viz.endpoints import router
from aind_metadata_viz.contributions.handlers import contributions_router
from aind_metadata_viz.acquisitions.handlers import acquisitions_router
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
]

app = FastAPI(openapi_tags=_OPENAPI_TAGS)

# The session cookie (set after ORCID login) must be sent on cross-origin
# requests from the frontend dev server. Browsers reject credentialed CORS
# with a wildcard origin, so when explicit origins are configured via
# ``CORS_ALLOW_ORIGINS`` we enable credentials; otherwise we keep the previous
# permissive, non-credentialed behavior for the public read endpoints.
_cors_origins_env = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
if _cors_origins_env:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors_origins_env.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Signed-cookie session, used to keep ORCID-authenticated users logged in.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=os.environ.get("SESSION_INSECURE", "").lower() not in ("1", "true"),
)

app.include_router(router)
app.include_router(auth_router)
app.include_router(contributions_router)
app.include_router(acquisitions_router)
app.include_router(chat_router)
app.include_router(summary_router)
mount_mcp_server(app)
