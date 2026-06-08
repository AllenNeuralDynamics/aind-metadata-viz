#!/usr/bin/env python3
"""
Integration test for the /retrieve-records endpoint.

Tests:
1. Empty query with names_only=true        -> returns 200 with asset_names list
2. Filter by project_name with names_only  -> returns 200 with asset_names list
3. Filter by modality with names_only      -> returns 200 with asset_names list
4. Query with limit                        -> returns 200 with limited asset_names
5. Full record retrieval with no projection -> returns 200 with full records
6. Invalid JSON body                       -> returns 400
7. Non-object body (array)                 -> returns 400

Usage:
    python test_retrieve_records_endpoint.py --env local    # Test against localhost:5006
    python test_retrieve_records_endpoint.py --env prod     # Test against production deployment
"""

import json
import sys

import requests
from aind_data_access_api.document_db import MetadataDbClient

from test_config import parse_test_args

DOCDB_CLIENT = MetadataDbClient(host="api.allenneuraldynamics.org", version="v2")


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

    print(f"Testing /retrieve-records endpoint against: {base_url}")
    print("=" * 80)

    all_passed = True

    # ------------------------------------------------------------------
    # Test 1: Empty query with names_only=true
    # ------------------------------------------------------------------
    print("\n[Test 1] Empty query with names_only=true")
    resp = requests.post(
        f"{base_url}/retrieve-records",
        json={},
        params={"names_only": "true", "limit": "5"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'asset_names'", "asset_names" in body, f"keys={list(body.keys())}")
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
        f"{base_url}/retrieve-records",
        json={"data_description.project_name": "Ephys Platform"},
        params={"names_only": "true", "limit": "10"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'asset_names'", "asset_names" in body, f"keys={list(body.keys())}")
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
        f"{base_url}/retrieve-records",
        json={"data_description.modality.abbreviation": {"$in": ["ecephys"]}},
        params={"names_only": "true", "limit": "10"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'asset_names'", "asset_names" in body, f"keys={list(body.keys())}")
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
        f"{base_url}/retrieve-records",
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
        f"{base_url}/retrieve-records",
        json={},
        params={"limit": "1"},
        timeout=30,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            passed &= check("Response contains 'records'", "records" in body, f"keys={list(body.keys())}")
            passed &= check("'records' is a list", isinstance(body.get("records"), list))
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
        f"{base_url}/retrieve-records",
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
        f"{base_url}/retrieve-records",
        json=["not", "an", "object"],
        timeout=30,
    )
    all_passed &= check("Status is 400", resp.status_code == 400, str(resp.status_code))

    # ------------------------------------------------------------------
    # Test 8: Cache returns same asset_names as direct DocDB v2
    #
    # Fetches the complete name set from both the endpoint (cache) and
    # DocDB with no limit, then compares them. Any mismatch indicates the
    # cache is stale or incorrect.
    # ------------------------------------------------------------------
    print("\n[Test 8] Cache asset_names match DocDB v2 (Ephys Platform, no limit)")
    test_filter = {"data_description.project_name": "Ephys Platform"}
    resp = requests.post(
        f"{base_url}/retrieve-records",
        json=test_filter,
        params={"names_only": "true"},
        timeout=60,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            endpoint_names = sorted(body.get("asset_names", []))
            passed &= check("Endpoint returned asset_names", len(endpoint_names) > 0, str(len(endpoint_names)))
            passed &= check("'backend' is present", "backend" in body, str(list(body.keys())))
            if passed:
                print(f"  (backend={body.get('backend')}, count={len(endpoint_names)})")
                docdb_records = DOCDB_CLIENT.retrieve_docdb_records(
                    filter_query=test_filter,
                    projection={"name": 1},
                )
                docdb_names = sorted(r["name"] for r in docdb_records if "name" in r)
                print(f"  (docdb count={len(docdb_names)})")
                only_in_endpoint = sorted(set(endpoint_names) - set(docdb_names))
                only_in_docdb = sorted(set(docdb_names) - set(endpoint_names))
                passed &= check(
                    "Cache and DocDB return same names",
                    endpoint_names == docdb_names,
                    f"only_in_cache={only_in_endpoint[:5]}, only_in_docdb={only_in_docdb[:5]}"
                    if endpoint_names != docdb_names else "",
                )
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

    # ------------------------------------------------------------------
    # Test 9: Cache count matches DocDB v2 for derived data_level
    # ------------------------------------------------------------------
    print("\n[Test 9] Cache count matches DocDB v2 (data_level=derived)")
    test_filter = {"data_description.data_level": "derived"}
    resp = requests.post(
        f"{base_url}/retrieve-records",
        json=test_filter,
        params={"names_only": "true"},
        timeout=60,
    )
    passed = check("Status is 200", resp.status_code == 200, str(resp.status_code))
    if passed:
        try:
            body = resp.json()
            endpoint_count = len(body.get("asset_names", []))
            passed &= check("Endpoint returned asset_names", endpoint_count > 0, str(endpoint_count))
            if passed:
                print(f"  (backend={body.get('backend')}, count={endpoint_count})")
                docdb_records = DOCDB_CLIENT.retrieve_docdb_records(
                    filter_query=test_filter,
                    projection={"name": 1},
                )
                docdb_count = len(docdb_records)
                print(f"  (docdb count={docdb_count})")
                passed &= check(
                    "Cache and DocDB counts match",
                    endpoint_count == docdb_count,
                    f"cache={endpoint_count}, docdb={docdb_count}",
                )
        except json.JSONDecodeError as exc:
            passed = False
            check("Response is valid JSON", False, str(exc))
    all_passed &= passed

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
