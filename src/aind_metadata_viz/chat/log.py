"""S3-backed chat request/response logger.

Appends one JSON Lines record per chat request to a daily log file in S3:
    s3://aind-scratch-data/aind-metadata-viz-logs/chat_log_{YYYY-MM-DD}.json

Each record contains:
    timestamp  – ISO-8601 UTC
    requester_id – optional caller-supplied identifier (from ?id= query param)
    ip         – client IP (may be None)
    message    – the incoming user message
    response   – the agent's reply text
    stop_reason
    iterations
    tool_call_count
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_S3_BUCKET = "aind-scratch-data"
_S3_PREFIX = "aind-metadata-viz-logs"


def _s3():
    return boto3.client("s3")


def _log_key(date_str: str) -> str:
    return f"{_S3_PREFIX}/chat_log_{date_str}.json"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_existing(key: str) -> bytes:
    try:
        resp = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
        body = resp["Body"].read()
        if not body.endswith(b"\n"):
            body += b"\n"
        return body
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return b""
        raise


def append_chat_log(
    *,
    message: str,
    response: str,
    stop_reason: str,
    iterations: int,
    tool_call_count: int,
    ip: Optional[str],
    requester_id: Optional[str],
) -> None:
    """Append a single chat record to today's S3 log file."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requester_id": requester_id,
        "ip": ip,
        "message": message,
        "response": response,
        "stop_reason": stop_reason,
        "iterations": iterations,
        "tool_call_count": tool_call_count,
    }
    line = (json.dumps(record) + "\n").encode()

    key = _log_key(_today_utc())
    try:
        existing = _get_existing(key)
        updated = existing + line
        _s3().put_object(
            Bucket=_S3_BUCKET,
            Key=key,
            Body=updated,
            ContentType="application/x-ndjson",
        )
    except Exception:
        logger.exception("Failed to write chat log to S3 key=%s", key)
