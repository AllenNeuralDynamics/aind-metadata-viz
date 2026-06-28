"""S3-backed chat & summary request/response logger.

Appends one JSON Lines record per request to a daily log file in S3:
    s3://aind-scratch-data/aind-metadata-viz-logs/chat_log_{YYYY-MM-DD}.json
    s3://aind-scratch-data/aind-metadata-viz-logs/summary_log_{YYYY-MM-DD}.json

Each chat record contains:
    timestamp  – ISO-8601 UTC
    requester_id – optional caller-supplied identifier (from ?id= query param)
    ip         – client IP (may be None)
    message    – the incoming user message
    response   – the agent's reply text
    stop_reason
    iterations
    tool_call_count

Each summary record contains:
    timestamp, requester_id, ip, name, summary, model_id, stop_reason,
    input_tokens, output_tokens, total_tokens, latency_ms,
    original_bytes, compacted_bytes, duration_ms, status_code
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


def _summary_log_key(date_str: str) -> str:
    return f"{_S3_PREFIX}/summary_log_{date_str}.json"


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


def _append_record(key: str, record: dict) -> None:
    """Append a single JSON record as a line to an S3 NDJSON file."""
    line = (json.dumps(record) + "\n").encode()
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
        logger.exception("Failed to write log to S3 key=%s", key)


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
    _append_record(_log_key(_today_utc()), record)


def append_summary_log(
    *,
    name: str,
    summary: str,
    model_id: str,
    stop_reason: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    latency_ms: int,
    original_bytes: int,
    compacted_bytes: int,
    duration_ms: int,
    status_code: int,
    ip: Optional[str],
    requester_id: Optional[str],
) -> None:
    """Append a single summary record to today's S3 log file."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requester_id": requester_id,
        "ip": ip,
        "name": name,
        "summary": summary,
        "model_id": model_id,
        "stop_reason": stop_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "original_bytes": original_bytes,
        "compacted_bytes": compacted_bytes,
        "duration_ms": duration_ms,
        "status_code": status_code,
    }
    _append_record(_summary_log_key(_today_utc()), record)
