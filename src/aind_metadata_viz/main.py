from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aind_metadata_viz.endpoints import router
from aind_metadata_viz.contributions.handlers import contributions_router
from aind_metadata_viz.acquisitions.handlers import acquisitions_router
from aind_metadata_viz.chat import chat_router, mount_mcp_server, summary_router

app = FastAPI()

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
