#!/usr/bin/env python3
"""
Integration test for the /upgrade-query endpoint.

Tests:
1. Valid message with no existing query -> returns 200 with a query dict
2. Valid message with an existing query  -> returns 200 with updated query dict
3. Missing message parameter             -> returns 400
4. Invalid JSON in query parameter       -> returns 400

Usage:
    python test_get_query_endpoint.py --env local    # Test against localhost:5006
    python test_get_query_endpoint.py --env prod     # Test against production deployment
"""

import json
import sys

import requests

from test_config import parse_test_args


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "✅" if condition else "❌"
    print(f"{status} {label}" + (f": {detail}" if detail else ""))
    return condition


def main():
    args = parse_test_args()
    base_url = (
        "https://metadata-portal.allenneuraldynamics-test.org"
        if args.env == "prod"
        else "http://localhost:5006"
    )

    print(f"Testing /upgrade-query endpoint against: {base_url}")
    print("=" * 80)

    all_passed = True

    # ------------------------------------------------------------------
    # Test 1: Valid message, no prior query
    # ------------------------------------------------------------------
    print("\n[Test 1] Valid message, no prior query")
    resp = requests.get(
        f"{base_url}/upgrade-query",
        params={"message": "show me all ecephys sessions"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'query' key", "query" in body, str(body))
            passed &= check(
                "'query' value is a dict", isinstance(body.get("query"), dict)
            )
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 2: Valid message with an existing query
    # ------------------------------------------------------------------
    print("\n[Test 2] Valid message with an existing query")
    existing_query = json.dumps({"subject.genotype": "wt/wt"})
    resp = requests.get(
        f"{base_url}/upgrade-query",
        params={
            "message": "also filter to sessions from 2024",
            "query": existing_query,
        },
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'query' key", "query" in body, str(body))
            passed &= check(
                "'query' value is a dict", isinstance(body.get("query"), dict)
            )
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 3: Missing message parameter -> 400
    # ------------------------------------------------------------------
    print("\n[Test 3] Missing message parameter")
    resp = requests.get(f"{base_url}/upgrade-query", timeout=30)
    all_passed &= check("Status is 400", resp.status_code == 400, str(resp.status_code))

    # ------------------------------------------------------------------
    # Test 4: Invalid JSON in query parameter -> 400
    # ------------------------------------------------------------------
    print("\n[Test 4] Invalid JSON in query parameter")
    resp = requests.get(
        f"{base_url}/upgrade-query",
        params={"message": "show me all ecephys sessions", "query": "{not valid json}"},
        timeout=30,
    )
    all_passed &= check("Status is 400", resp.status_code == 400, str(resp.status_code))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ All tests passed.")
    else:
        print("❌ Some tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
