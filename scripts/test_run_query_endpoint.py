#!/usr/bin/env python3
"""
Integration test for the /get-query endpoint.

Tests:
1. Empty query with names_only=true        -> returns 200 with asset_names list
2. Filter by project_name with names_only  -> returns 200 with asset_names list
3. Filter by modality with names_only      -> returns 200 with asset_names list
4. Query with limit                        -> returns 200 with limited asset_names
5. Full record retrieval with no projection -> returns 200 with full records
6. Invalid JSON body                       -> returns 400
7. Non-object body (array)                 -> returns 400

Usage:
    python test_run_query_endpoint.py --env local    # Test against localhost:5006
    python test_run_query_endpoint.py --env prod     # Test against production deployment
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
    # Test 1: Empty query with names_only=true
    # ------------------------------------------------------------------
    print("\n[Test 1] Empty query with names_only=true")
    resp = requests.post(
        f"{base_url}/get-query",
        json={},
        params={"names_only": "true", "limit": "5"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'asset_names'", "asset_names" in body, str(body))
            passed &= check(
                "'asset_names' is a list", isinstance(body.get("asset_names"), list)
            )
            passed &= check("'records' not present (names_only)", "records" not in body)
            passed &= check("'backend' is present", "backend" in body)
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 2: Filter by project_name with names_only
    # ------------------------------------------------------------------
    print("\n[Test 2] Filter by data_description.project_name with names_only")
    resp = requests.post(
        f"{base_url}/get-query",
        json={"data_description.project_name": "Ephys Platform"},
        params={"names_only": "true", "limit": "10"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'asset_names'", "asset_names" in body, str(body))
            passed &= check(
                "'asset_names' is a list", isinstance(body.get("asset_names"), list)
            )
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 3: Filter by modality abbreviation with names_only
    # ------------------------------------------------------------------
    print("\n[Test 3] Filter by modality abbreviation with names_only")
    resp = requests.post(
        f"{base_url}/get-query",
        json={"data_description.modality.abbreviation": {"$in": ["ecephys"]}},
        params={"names_only": "true", "limit": "10"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'asset_names'", "asset_names" in body, str(body))
            passed &= check(
                "'asset_names' is a list", isinstance(body.get("asset_names"), list)
            )
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 4: Query with limit enforced
    # ------------------------------------------------------------------
    print("\n[Test 4] Query with limit=3 enforced")
    resp = requests.post(
        f"{base_url}/get-query",
        json={},
        params={"names_only": "true", "limit": "3"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            names = body.get("asset_names", [])
            passed &= check("asset_names has <= 3 items", len(names) <= 3, str(len(names)))
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 5: Full record retrieval with no projection
    # ------------------------------------------------------------------
    print("\n[Test 5] Full record retrieval with no projection")
    resp = requests.post(
        f"{base_url}/get-query",
        json={},
        params={"limit": "1"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'records'", "records" in body, str(body))
            passed &= check("'records' is a list", isinstance(body.get("records"), list))
            passed &= check("'asset_names' not present", "asset_names" not in body)
            if body.get("records"):
                record = body["records"][0]
                passed &= check(
                    "Record has data_description", "data_description" in record
                )
                passed &= check("Record has subject", "subject" in record)
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 6: Invalid JSON body -> 400
    # ------------------------------------------------------------------
    print("\n[Test 6] Invalid JSON body")
    resp = requests.post(
        f"{base_url}/get-query",
        data="not valid json",
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    all_passed &= check("Status is 400", resp.status_code == 400, str(resp.status_code))

    # ------------------------------------------------------------------
    # Test 7: Non-object body (array) -> 400
    # ------------------------------------------------------------------
    print("\n[Test 7] Non-object body (array)")
    resp = requests.post(
        f"{base_url}/get-query",
        json=["not", "an", "object"],
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
