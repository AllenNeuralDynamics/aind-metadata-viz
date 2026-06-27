"""Mount the aind-data-mcp FastMCP server as an HTTP endpoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Import side-effect: registers tools on the shared mcp instance and
# disables the NWB tools that we don't want exposed.
from . import tools as _tools  # noqa: F401
from aind_data_mcp.mcp_instance import mcp

from .ratelimit import RateLimiter, client_ip
from .security import ALLOWED_ORIGIN_REGEX, origin_error

logger = logging.getLogger(__name__)

MCP_MOUNT_PATH = os.environ.get("MCP_MOUNT_PATH", "/mcp")

# 1 request/second sustained. A small burst lets the MCP protocol
# handshake (initialize -> list tools -> call) proceed without tripping
# the limiter on the first interaction.
mcp_rate_limiter = RateLimiter(
    per_minute=int(os.environ.get("MCP_RATE_PER_MIN", "60")),
    per_day=int(os.environ.get("MCP_RATE_PER_DAY", "1000")),
    burst=int(os.environ.get("MCP_RATE_BURST", "5")),
)


class _MCPSecurityMiddleware(BaseHTTPMiddleware):
    """Enforce Origin allow-listing and per-IP rate limiting for MCP."""

    async def dispatch(self, request, call_next):
        blocked = origin_error(request.headers)
        if blocked:
            return JSONResponse(status_code=403, content={"error": blocked})

        ip = client_ip(
            request.headers,
            request.client.host if request.client else None,
        )
        allowed, error = mcp_rate_limiter.check("mcp", ip)
        if not allowed:
            return JSONResponse(status_code=429, content={"error": error})
        return await call_next(request)


def mount_mcp_server(app: FastAPI) -> None:
    """Mount the FastMCP HTTP app onto ``app`` and wire up lifespan."""

    mcp_app = mcp.http_app(path="/")
    mcp_app.add_middleware(_MCPSecurityMiddleware)
    mcp_app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=ALLOWED_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # FastMCP requires its session manager to start via the ASGI lifespan
    # event. When mounted under FastAPI, we must propagate the inner
    # lifespan or tool calls will fail with "session manager not started".
    existing_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(scope_app: FastAPI):
        # mcp_app.lifespan is already an @asynccontextmanager-decorated
        # factory — call it with the sub-app to get the context manager.
        async with mcp_app.lifespan(mcp_app):
            async with existing_lifespan(scope_app):
                yield

    app.router.lifespan_context = combined_lifespan
    app.mount(MCP_MOUNT_PATH, mcp_app)
    logger.info("Mounted FastMCP server at %s", MCP_MOUNT_PATH)
