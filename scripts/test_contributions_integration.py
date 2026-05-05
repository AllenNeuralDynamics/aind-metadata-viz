"""Integration test: full contributions lifecycle against the production server.

Steps
-----
1.  POST v1  — minimal project (one contributor, no password)
2.  GET      — verify project is readable and not locked
3.  POST v2  — add a second contributor and DOI; supply password to lock the project
4.  GET      — verify second contributor, DOI, and locked=True (still readable)
5.  POST     — attempt re-save without password → expect 401
6.  POST v3  — re-save with correct password; add third contributor
7.  GET      — verify all three contributors present

Usage
-----
    python scripts/test_contributions_integration.py
"""

import json
import sys
import time

import requests

BASE_URL = "https://metadata-portal.allenneuraldynamics.org"
PROJECT = f"integration-test-lifecycle-{int(time.time())}"
PASSWORD = "sha256-integration-test-hash"
GET_URL = f"{BASE_URL}/contributions/get"
POST_URL = f"{BASE_URL}/contributions/post"

print(f"Testing against: {BASE_URL}")
print("=" * 60)


def sep(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def check(response, expected_status):
    if response.status_code != expected_status:
        print(f"  FAIL  status={response.status_code}  body={response.text[:400]}")
        sys.exit(1)
    print(f"  OK    status={response.status_code}")
    try:
        return response.json()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Step 1: POST v1 — minimal project, no password
# ---------------------------------------------------------------------------

V1 = {
    "project_name": PROJECT,
    "contributors": [
        {
            "author": {
                "name": "Alice Nguyen",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0001-2345-6789",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "conceptualization", "level": "lead"},
            ],
        }
    ],
}

sep("Step 1: POST v1 (one contributor, no password)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=initial+version",
    data=json.dumps(V1).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v1 = check(r, 200)
commit_v1 = v1["commit"]
print(f"  commit v1: {commit_v1[:12]}")

# ---------------------------------------------------------------------------
# Step 2: GET — verify readable and not locked
# ---------------------------------------------------------------------------

sep("Step 2: GET (no password, should be 200 and not locked)")
r = requests.get(GET_URL, params={"project": PROJECT})
data = check(r, 200)
assert data["project_name"] == PROJECT
assert len(data["contributors"]) == 1
assert data.get("locked") is False, f"expected locked=False, got {data.get('locked')}"
print(f"  contributors: {[c['author']['name'] for c in data['contributors']]}")
print(f"  locked: {data.get('locked')}")

# ---------------------------------------------------------------------------
# Step 3: POST v2 — add second contributor + DOI, supply password to lock
# ---------------------------------------------------------------------------

V2 = {
    "project_name": PROJECT,
    "doi": "10.1234/integration-test",
    "contributors": [
        {
            "author": {
                "name": "Alice Nguyen",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0001-2345-6789",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "conceptualization", "level": "lead"},
                {"role": "writing-original-draft", "level": "lead"},
            ],
        },
        {
            "author": {
                "name": "Bob Okafor",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0002-3456-7890",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "data-curation", "level": "equal"},
            ],
        },
    ],
}

sep("Step 3: POST v2 (add Bob + DOI, supply password → locks project)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=add+bob+and+doi&password={PASSWORD}",
    data=json.dumps(V2).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v2 = check(r, 200)
commit_v2 = v2["commit"]
print(f"  commit v2: {commit_v2[:12]}")

# ---------------------------------------------------------------------------
# Step 4: GET — locked project still publicly readable
# ---------------------------------------------------------------------------

sep("Step 4: GET (locked project, no password — should still be 200)")
r = requests.get(GET_URL, params={"project": PROJECT})
data = check(r, 200)
names = [c["author"]["name"] for c in data["contributors"]]
assert len(names) == 2, f"expected 2 contributors, got {names}"
assert data.get("doi") == "10.1234/integration-test"
assert data.get("locked") is True, f"expected locked=True, got {data.get('locked')}"
print(f"  contributors: {names}")
print(f"  doi: {data.get('doi')}")
print(f"  locked: {data.get('locked')}")

# ---------------------------------------------------------------------------
# Step 5: POST without password → 401
# ---------------------------------------------------------------------------

sep("Step 5: POST without password on locked project (expect 401)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=should+fail",
    data=json.dumps(V2).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
check(r, 401)

# ---------------------------------------------------------------------------
# Step 6: POST v3 — correct password, add third contributor + sections
# ---------------------------------------------------------------------------

V3 = {
    "project_name": PROJECT,
    "doi": "10.1234/integration-test",
    "contributors": [
        {
            "author": {
                "name": "Alice Nguyen",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0001-2345-6789",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "conceptualization", "level": "lead"},
                {"role": "writing-original-draft", "level": "lead"},
            ],
        },
        {
            "author": {
                "name": "Bob Okafor",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0002-3456-7890",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "data-curation", "level": "equal"},
            ],
        },
        {
            "author": {
                "name": "Carmen Silva",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0003-4567-8901",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "visualization", "level": "lead"},
                {"role": "writing-review-editing", "level": "supporting"},
            ],
        },
    ],
    "sections": ["Introduction", "Methods", "Results"],
}

sep("Step 6: POST v3 (correct password, add Carmen + sections)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=add+carmen+and+sections&password={PASSWORD}",
    data=json.dumps(V3).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v3 = check(r, 200)
commit_v3 = v3["commit"]
print(f"  commit v3: {commit_v3[:12]}")

# ---------------------------------------------------------------------------
# Step 7: GET — verify all three contributors, sections, still locked
# ---------------------------------------------------------------------------

sep("Step 7: GET (verify 3 contributors, sections, still locked)")
r = requests.get(GET_URL, params={"project": PROJECT})
data = check(r, 200)
names = [c["author"]["name"] for c in data["contributors"]]
assert len(names) == 3, f"expected 3 contributors, got {names}"
assert data.get("sections") == ["Introduction", "Methods", "Results"]
assert data.get("locked") is True
print(f"  contributors: {names}")
print(f"  sections: {data.get('sections')}")
print(f"  locked: {data.get('locked')}")

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
