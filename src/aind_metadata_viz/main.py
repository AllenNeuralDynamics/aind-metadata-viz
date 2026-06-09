from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aind_metadata_viz.endpoints import router
from aind_metadata_viz.contributions.handlers import contributions_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(contributions_router)
