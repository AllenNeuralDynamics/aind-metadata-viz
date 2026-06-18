#!/usr/bin/env python3
"""
Integration test for chat endpoint logging to S3.

Sends a chat request with a known ?id= value, then reads the daily S3 log
file and verifies that the record was written with the correct fields.

Usage:
    python test_log_integration.py --env local
    python test_log_integration.py --env prod

Requires:
    - A running server (local or prod).
    - AWS credentials with s3:GetObject / s3:PutObject on
      s3://aind-scratch-data/aind-metadata-viz-logs/*.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone

import boto3
import requests

from test_config import parse_test_args

_S3_BUCKET = "aind-scratch-data"
_S3_PREFIX = "aind-metadata-viz-logs"


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}" + (f": {detail}" if detail else ""))
    return condition


def _log_key(date_str: str) -> str:
    return f"{_S3_PREFIX}/chat_log_{date_str}.json"


def _read_log_lines(date_str: str) -> list[dict]:
    s3 = boto3.client("s3")
    try:
        resp = s3.get_object(Bucket=_S3_BUCKET, Key=_log_key(date_str))
        raw = resp["Body"].read().decode()
    except s3.exceptions.NoSuchKey:
        return []
    except Exception as exc:
        print(f"[WARN] Could not read S3 log: {exc}")
        return []
    records = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def run_log_tests(base_url: str) -> bool:
    all_passed = True
    chat_url = f"{base_url}/chat"
    requester_id = f"log-integration-test-{uuid.uuid4().hex[:8]}"
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"\n--- Chat log integration tests (id={requester_id}) ---")

    print("\n[Test 1] POST /chat with ?id= writes a log record to S3")
    resp = requests.post(
        chat_url,
        params={"id": requester_id},
        json={"message": "Say the word 'hello' and nothing else."},
        timeout=120,
    )
    passed = check("Status 200", resp.status_code == 200, str(resp.status_code))
    if not passed:
        print(f"  Response: {resp.text[:200]}")
        all_passed = False
        return all_passed

    agent_response = resp.json().get("response", "")
    passed &= check("response non-empty", bool(agent_response))
    all_passed &= passed

    print("\n[Test 2] Log record exists in S3 with correct fields")
    records = _read_log_lines(today_utc)
    matching = [r for r in records if r.get("requester_id") == requester_id]
    passed = check(
        "at least one log record with requester_id",
        len(matching) >= 1,
        f"{len(matching)} found",
    )
    all_passed &= passed

    if matching:
        record = matching[-1]
        all_passed &= check(
            "timestamp present",
            bool(record.get("timestamp")),
            record.get("timestamp", ""),
        )
        all_passed &= check(
            "message matches",
            record.get("message") == "Say the word 'hello' and nothing else.",
        )
        all_passed &= check(
            "response matches agent response",
            record.get("response") == agent_response,
        )
        all_passed &= check(
            "stop_reason present", bool(record.get("stop_reason"))
        )
        all_passed &= check(
            "iterations is int", isinstance(record.get("iterations"), int)
        )
        all_passed &= check(
            "tool_call_count is int",
            isinstance(record.get("tool_call_count"), int),
        )

    print("\n[Test 3] POST /chat without ?id= logs requester_id as null")
    null_id_marker = f"null-id-test-{uuid.uuid4().hex[:8]}"
    resp2 = requests.post(
        chat_url,
        json={"message": f"Reply with the exact phrase: {null_id_marker}"},
        timeout=120,
    )
    passed = check("Status 200", resp2.status_code == 200, str(resp2.status_code))
    if passed:
        records2 = _read_log_lines(today_utc)
        null_id_records = [
            r
            for r in records2
            if r.get("requester_id") is None
            and null_id_marker in r.get("message", "")
        ]
        all_passed &= check(
            "record with null requester_id written",
            len(null_id_records) >= 1,
            f"{len(null_id_records)} found",
        )
    all_passed &= passed

    return all_passed


def main() -> None:
    args = parse_test_args()
    base_url = (
        "https://metadata-portal.allenneuraldynamics-test.org"
        if args.env == "prod"
        else "http://localhost:5006"
    )

    print(f"Testing chat logging against: {base_url}")
    print(f"S3 log bucket: s3://{_S3_BUCKET}/{_S3_PREFIX}/")
    print("=" * 80)

    ok = run_log_tests(base_url)

    print("\n" + "=" * 80)
    if ok:
        print("All log integration tests passed.")
    else:
        print("Some log integration tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
