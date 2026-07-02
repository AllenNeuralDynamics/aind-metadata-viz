from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aind_metadata_viz.endpoints import router
from aind_metadata_viz.contributions.handlers import contributions_router
from aind_metadata_viz.acquisitions.handlers import acquisitions_router
from aind_metadata_viz.chat import chat_router, mount_mcp_server, summary_router

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(contributions_router)
app.include_router(acquisitions_router)
app.include_router(chat_router)
app.include_router(summary_router)
mount_mcp_server(app)
