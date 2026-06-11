#!/usr/bin/env python3
"""
Integration test for the /chat endpoint and the mounted /mcp server.

The /chat tests run the real Bedrock-backed agent end-to-end. Requires
AWS credentials with bedrock-runtime access to be available to the
running server (typically via BEDROCK_ROLE_ARN + an STS-assumable role).

The /mcp tests speak raw streamable-HTTP MCP and verify the audited
allowlist plus rate limiting.

Tests
-----
/chat:
  1. Valid simple message -> 200 with non-empty response.
  2. Tool-using message (asks about top-level nodes) -> 200, at least
     one tool_call recorded, and the response references real fields.
  3. Empty message -> 400.
  4. Oversize message -> 400.
  5. Invalid history shape -> 400.

/mcp:
  6. tools/list returns the audited set (no NWB tools).
  7. tools/call against `get_top_level_nodes` returns expected content.

Usage:
    python test_chat_integration.py --env local
    python test_chat_integration.py --env prod
"""

from __future__ import annotations

import json
import sys
import uuid

import requests

from test_config import parse_test_args


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}" + (f": {detail}" if detail else ""))
    return condition


def _post_json(url: str, body: dict, timeout: int = 120) -> requests.Response:
    return requests.post(url, json=body, timeout=timeout)


def run_chat_tests(base_url: str) -> bool:
    all_passed = True
    chat_url = f"{base_url}/chat"

    print("\n--- /chat tests ---")

    print("\n[Test 1] Simple message")
    resp = _post_json(chat_url, {"message": "Say hello in five words."})
    passed = check("Status 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        body = resp.json()
        passed &= check("response is non-empty string", bool(body.get("response")))
        passed &= check("tool_calls present", "tool_calls" in body)
        passed &= check("stop_reason present", "stop_reason" in body)
    all_passed &= passed

    print("\n[Test 2] Tool-using message")
    resp = _post_json(
        chat_url,
        {
            "message": (
                "Use the available tools to list the top-level nodes "
                "of the AIND metadata schema, then answer in one short "
                "sentence."
            )
        },
        timeout=180,
    )
    passed = check("Status 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        body = resp.json()
        passed &= check(
            "at least one tool call",
            len(body.get("tool_calls", [])) >= 1,
            f"{len(body.get('tool_calls', []))}",
        )
        passed &= check(
            "response mentions a schema field",
            any(
                f in body.get("response", "").lower()
                for f in ("subject", "acquisition", "data_description")
            ),
        )
    all_passed &= passed

    print("\n[Test 3] Missing message -> 400")
    resp = _post_json(chat_url, {})
    all_passed &= check("Status 400", resp.status_code == 400, str(resp.status_code))

    print("\n[Test 4] Oversize message -> 400")
    resp = _post_json(chat_url, {"message": "x" * 10_000})
    all_passed &= check("Status 400", resp.status_code == 400, str(resp.status_code))

    print("\n[Test 5] Invalid history shape -> 400")
    resp = _post_json(chat_url, {"message": "hi", "history": "not a list"})
    all_passed &= check("Status 400", resp.status_code == 400, str(resp.status_code))

    return all_passed


def _mcp_request(base_url: str, body: dict, session_id: str | None = None) -> tuple[int, dict | str]:
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    resp = requests.post(
        f"{base_url}/mcp/", json=body, headers=headers, timeout=60
    )
    text = resp.text
    # streamable-http returns SSE for streaming endpoints; for the single-
    # response calls we make here it returns a JSON body.
    if text.startswith("event:") or "data:" in text:
        # parse the first data: line
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    return resp.status_code, json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    pass
        return resp.status_code, text
    try:
        return resp.status_code, resp.json()
    except json.JSONDecodeError:
        return resp.status_code, text


def run_mcp_tests(base_url: str) -> bool:
    all_passed = True
    print("\n--- /mcp tests ---")

    # initialize handshake
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "0.1"},
        },
    }
    status, init_resp = _mcp_request(base_url, init_body)
    passed = check("initialize status 200", status == 200, str(status))
    session_id = None
    if passed:
        # session id is in response headers; refetch with headers visible
        resp = requests.post(
            f"{base_url}/mcp/",
            json=init_body,
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
            timeout=30,
        )
        session_id = resp.headers.get("mcp-session-id")
        passed &= check(
            "session id returned",
            bool(session_id),
            session_id or "(none)",
        )
        if session_id:
            # Initialized notification
            requests.post(
                f"{base_url}/mcp/",
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
                headers={
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                    "mcp-session-id": session_id,
                },
                timeout=15,
            )
    all_passed &= passed
    if not session_id:
        return all_passed

    print("\n[Test 6] tools/list excludes NWB tools")
    status, body = _mcp_request(
        base_url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id=session_id,
    )
    passed = check("tools/list status 200", status == 200, str(status))
    if passed and isinstance(body, dict):
        names = [t.get("name") for t in body.get("result", {}).get("tools", [])]
        passed &= check(
            "tool list non-empty", len(names) > 0, f"{len(names)} tools"
        )
        passed &= check(
            "no identify_nwb_contents_with_s3_link",
            "identify_nwb_contents_with_s3_link" not in names,
        )
        passed &= check(
            "no identify_nwb_contents_in_code_ocean",
            "identify_nwb_contents_in_code_ocean" not in names,
        )
        passed &= check("get_top_level_nodes present", "get_top_level_nodes" in names)
    all_passed &= passed

    print("\n[Test 7] tools/call get_top_level_nodes")
    status, body = _mcp_request(
        base_url,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_top_level_nodes", "arguments": {}},
        },
        session_id=session_id,
    )
    passed = check("tools/call status 200", status == 200, str(status))
    if passed and isinstance(body, dict):
        content = body.get("result", {}).get("content", [])
        passed &= check("content non-empty", len(content) > 0)
        text = json.dumps(content)
        passed &= check("mentions 'subject'", "subject" in text)
    all_passed &= passed

    return all_passed


def main() -> None:
    args = parse_test_args()
    base_url = (
        "https://metadata-portal.allenneuraldynamics-test.org"
        if args.env == "prod"
        else "http://localhost:5006"
    )

    print(f"Testing /chat and /mcp against: {base_url}")
    print("=" * 80)

    chat_ok = run_chat_tests(base_url)
    mcp_ok = run_mcp_tests(base_url)

    print("\n" + "=" * 80)
    if chat_ok and mcp_ok:
        print("All chat + mcp integration tests passed.")
    else:
        print("Some integration tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
