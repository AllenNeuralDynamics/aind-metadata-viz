"""POST /chat handler with input validation and per-IP rate limiting."""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .agent import result_to_dict, run_agent
from .log import append_chat_log
from .ratelimit import RateLimiter, client_ip

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = int(os.environ.get("CHAT_MAX_MESSAGE_BYTES", "4096"))
MAX_HISTORY_TURNS = int(os.environ.get("CHAT_MAX_HISTORY_TURNS", "20"))

chat_rate_limiter = RateLimiter(
    per_minute=int(os.environ.get("CHAT_RATE_PER_MIN", "10")),
    per_day=int(os.environ.get("CHAT_RATE_PER_DAY", "200")),
)

chat_router = APIRouter()


def _validate(data) -> tuple[str | None, dict | None]:
    """Return (error_message, validated_payload). One is always None."""
    if not isinstance(data, dict):
        return "Request body must be a JSON object.", None

    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return "'message' is required and must be a non-empty string.", None
    if len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return (
            f"'message' exceeds maximum length of {MAX_MESSAGE_BYTES} bytes.",
            None,
        )

    history = data.get("history")
    if history is not None:
        if not isinstance(history, list):
            return "'history' must be a list of turn objects.", None
        if len(history) > MAX_HISTORY_TURNS:
            return (
                f"'history' exceeds maximum of {MAX_HISTORY_TURNS} turns.",
                None,
            )
        for i, turn in enumerate(history):
            if not isinstance(turn, dict):
                return f"'history[{i}]' must be an object.", None
            if turn.get("role") not in ("user", "assistant"):
                return (
                    f"'history[{i}].role' must be 'user' or 'assistant'.",
                    None,
                )
            if not isinstance(turn.get("content"), str):
                return (
                    f"'history[{i}].content' must be a string.",
                    None,
                )

    return None, {"message": message, "history": history or []}


@chat_router.post("/chat")
async def chat_endpoint(
    request: Request,
    id: Optional[str] = Query(default=None, description="Optional caller identifier"),
):
    ip = client_ip(
        request.headers, request.client.host if request.client else None
    )
    allowed, error = chat_rate_limiter.check("chat", ip)
    if not allowed:
        return JSONResponse(status_code=429, content={"error": error})

    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400, content={"error": "Invalid JSON body."}
        )

    err, payload = _validate(data)
    if err:
        return JSONResponse(status_code=400, content={"error": err})

    logger.info(
        "chat request ip=%s msg_len=%d history_len=%d",
        ip,
        len(payload["message"]),
        len(payload["history"]),
    )

    try:
        result = await run_agent(
            payload["message"], history=payload["history"]
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat agent failed")
        return JSONResponse(
            status_code=500,
            content={"error": "Agent run failed", "details": str(exc)},
        )

    logger.info(
        "chat response ip=%s stop=%s iters=%d tools=%d",
        ip,
        result.stop_reason,
        result.iterations,
        len(result.tool_calls),
    )
    append_chat_log(
        message=payload["message"],
        response=result_to_dict(result).get("response", ""),
        stop_reason=result.stop_reason,
        iterations=result.iterations,
        tool_call_count=len(result.tool_calls),
        ip=ip,
        requester_id=id,
    )
    return JSONResponse(content=result_to_dict(result))
