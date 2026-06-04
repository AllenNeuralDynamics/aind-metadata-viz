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
DOI = f"10.1234/integration-test-{int(time.time())}"
PASSWORD = "sha256-integration-test-hash"
GET_URL = f"{BASE_URL}/contributions/get"
POST_URL = f"{BASE_URL}/contributions/post"
TOKEN_URL = f"{BASE_URL}/contributions/token"

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
    "doi": DOI,
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
assert data.get("doi") == DOI
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
    "doi": DOI,
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

# ---------------------------------------------------------------------------
# Step 8: Create add_author token without password on locked project → 401
# ---------------------------------------------------------------------------

sep("Step 8: GET token without password on locked project (expect 401)")
r = requests.get(
    TOKEN_URL,
    params={"doi": DOI, "type": "add_author"},
)
check(r, 401)

# ---------------------------------------------------------------------------
# Step 9: Create add_author token with correct password → 200
# ---------------------------------------------------------------------------

sep("Step 9: GET add_author token with correct password (expect 200)")
r = requests.get(
    TOKEN_URL,
    params={
        "doi": DOI,
        "type": "add_author",
        "password": PASSWORD,
    },
)
token_data = check(r, 200)
assert token_data["type"] == "add_author"
assert "token" in token_data
assert token_data["expires_days"] == 365
add_author_token = token_data["token"]
print(f"  token: {add_author_token[:12]}...")
print(f"  type: {token_data['type']}")
print(f"  expires_days: {token_data['expires_days']}")

# ---------------------------------------------------------------------------
# Step 10: Use add_author token to add a 4th contributor (Diana)
# ---------------------------------------------------------------------------

V4 = {
    "project_name": PROJECT,
    "doi": DOI,
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
        {
            "author": {
                "name": "Diana Park",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0004-5678-9012",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "software", "level": "lead"},
            ],
        },
    ],
    "sections": ["Introduction", "Methods", "Results"],
}

sep("Step 10: POST v4 using add_author token (add Diana)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=add+diana&password={add_author_token}",
    data=json.dumps(V4).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v4 = check(r, 200)
print(f"  commit v4: {v4['commit'][:12]}")

# ---------------------------------------------------------------------------
# Step 11: GET — verify all four contributors present
# ---------------------------------------------------------------------------

sep("Step 11: GET (verify 4 contributors after add_author token use)")
r = requests.get(GET_URL, params={"project": PROJECT})
data = check(r, 200)
names = [c["author"]["name"] for c in data["contributors"]]
assert len(names) == 4, f"expected 4 contributors, got {names}"
assert "Diana Park" in names
print(f"  contributors: {names}")

# ---------------------------------------------------------------------------
# Step 12: Try to reuse the consumed add_author token → 401
# ---------------------------------------------------------------------------

sep("Step 12: POST with consumed add_author token (expect 401)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=reuse+token&password={add_author_token}",
    data=json.dumps(V4).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
check(r, 401)

# ---------------------------------------------------------------------------
# Step 13: Create edit_author token without author param → 400
# ---------------------------------------------------------------------------

sep("Step 13: GET edit_author token without author param (expect 400)")
r = requests.get(
    TOKEN_URL,
    params={
        "doi": DOI,
        "type": "edit_author",
        "password": PASSWORD,
    },
)
check(r, 400)

# ---------------------------------------------------------------------------
# Step 14: Create edit_author token for Carmen Silva → 200
# ---------------------------------------------------------------------------

sep("Step 14: GET edit_author token for Carmen Silva (expect 200)")
r = requests.get(
    TOKEN_URL,
    params={
        "doi": DOI,
        "type": "edit_author",
        "author": "Carmen Silva",
        "days": "30",
        "password": PASSWORD,
    },
)
ea_data = check(r, 200)
assert ea_data["type"] == "edit_author"
assert "token" in ea_data
assert ea_data["expires_days"] == 30
edit_author_token = ea_data["token"]
print(f"  token: {edit_author_token[:12]}...")
print(f"  type: {ea_data['type']}")
print(f"  expires_days: {ea_data['expires_days']}")

# ---------------------------------------------------------------------------
# Step 15: Use edit_author token to modify Carmen's credits
# ---------------------------------------------------------------------------

V5 = {
    "project_name": PROJECT,
    "doi": DOI,
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
                {"role": "writing-review-editing", "level": "lead"},
                {"role": "software", "level": "supporting"},
            ],
        },
        {
            "author": {
                "name": "Diana Park",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0004-5678-9012",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [
                {"role": "software", "level": "lead"},
            ],
        },
    ],
    "sections": ["Introduction", "Methods", "Results"],
}

sep("Step 15: POST v5 using edit_author token (modify Carmen's credits)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=edit+carmen&password={edit_author_token}",
    data=json.dumps(V5).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v5 = check(r, 200)
print(f"  commit v5: {v5['commit'][:12]}")

# ---------------------------------------------------------------------------
# Step 16: GET — verify Carmen changed; all four contributors still present
# ---------------------------------------------------------------------------

sep("Step 16: GET (verify Carmen updated, 4 contributors still present)")
r = requests.get(GET_URL, params={"project": PROJECT})
data = check(r, 200)
names = [c["author"]["name"] for c in data["contributors"]]
assert len(names) == 4, f"expected 4 contributors, got {names}"
carmen = next(c for c in data["contributors"] if c["author"]["name"] == "Carmen Silva")
carmen_roles = [cr["role"] for cr in carmen["credit_levels"]]
assert "software" in carmen_roles, f"expected software role for Carmen, got {carmen_roles}"
print(f"  contributors: {names}")
print(f"  Carmen roles: {carmen_roles}")

# ---------------------------------------------------------------------------
# Step 17: Try to use edit_author token to add a new contributor → 403
# ---------------------------------------------------------------------------

V5_add = {
    **V5,
    "contributors": V5["contributors"] + [
        {
            "author": {
                "name": "Evan Torres",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0005-6789-0123",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [{"role": "investigation", "level": "equal"}],
        }
    ],
}

sep("Step 17: POST with edit_author token adding a new author (expect 403)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=add+evan+via+edit+token&password={edit_author_token}",
    data=json.dumps(V5_add).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
check(r, 403)

# ---------------------------------------------------------------------------
# Step 18: edit_author token is still reusable — can edit Carmen again
# ---------------------------------------------------------------------------

sep("Step 18: POST with edit_author token again (reusable, expect 200)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=carmen+second+edit&password={edit_author_token}",
    data=json.dumps(V5).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v6 = check(r, 200)
print(f"  commit v6: {v6['commit'][:12]}")

# ---------------------------------------------------------------------------
# Step 19: Create multi_author token capped at 7 days → 200
# ---------------------------------------------------------------------------

sep("Step 19: GET multi_author token (expect 200, expires_days <= 7)")
r = requests.get(
    TOKEN_URL,
    params={
        "doi": DOI,
        "type": "multi_author",
        "days": "9999",
        "password": PASSWORD,
    },
)
ma_data = check(r, 200)
assert ma_data["type"] == "multi_author"
assert "token" in ma_data
assert ma_data["expires_days"] <= 7, f"expected expires_days <= 7, got {ma_data['expires_days']}"
multi_author_token = ma_data["token"]
print(f"  token: {multi_author_token[:12]}...")
print(f"  expires_days: {ma_data['expires_days']}")

# ---------------------------------------------------------------------------
# Step 20: First person uses multi_author token to add Evan Torres
# ---------------------------------------------------------------------------

V7 = {
    "project_name": PROJECT,
    "doi": DOI,
    "contributors": V5["contributors"] + [
        {
            "author": {
                "name": "Evan Torres",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0005-6789-0123",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [{"role": "investigation", "level": "equal"}],
        }
    ],
    "sections": ["Introduction", "Methods", "Results"],
}

sep("Step 20: POST using multi_author token (first use — add Evan, expect 200)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=add+evan+via+multi+token&password={multi_author_token}",
    data=json.dumps(V7).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v7 = check(r, 200)
print(f"  commit v7: {v7['commit'][:12]}")

# ---------------------------------------------------------------------------
# Step 21: Second person uses the same token to add Fatima (reusable)
# ---------------------------------------------------------------------------

V8 = {
    "project_name": PROJECT,
    "doi": DOI,
    "contributors": V7["contributors"] + [
        {
            "author": {
                "name": "Fatima Hassan",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0006-7890-1234",
                "affiliation": ["Allen Institute for Neural Dynamics"],
            },
            "credit_levels": [{"role": "validation", "level": "equal"}],
        }
    ],
    "sections": ["Introduction", "Methods", "Results"],
}

sep("Step 21: POST using same multi_author token (second use — add Fatima, expect 200)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=add+fatima+via+multi+token&password={multi_author_token}",
    data=json.dumps(V8).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v8 = check(r, 200)
print(f"  commit v8: {v8['commit'][:12]}")

# ---------------------------------------------------------------------------
# Step 22: GET — verify Evan and Fatima both added
# ---------------------------------------------------------------------------

sep("Step 22: GET (verify Evan and Fatima present)")
r = requests.get(GET_URL, params={"project": PROJECT})
data = check(r, 200)
names = [c["author"]["name"] for c in data["contributors"]]
assert "Evan Torres" in names, f"Evan Torres not found in {names}"
assert "Fatima Hassan" in names, f"Fatima Hassan not found in {names}"
print(f"  contributors: {names}")

# ---------------------------------------------------------------------------
# Step 23: multi_author token cannot remove an existing author → 403
# ---------------------------------------------------------------------------

V8_remove = {**V8, "contributors": [c for c in V8["contributors"] if c["author"]["name"] != "Alice Nguyen"]}

sep("Step 23: POST with multi_author token removing an author (expect 403)")
r = requests.post(
    f"{POST_URL}?project={PROJECT}&message=remove+alice+via+multi+token&password={multi_author_token}",
    data=json.dumps(V8_remove).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
check(r, 403)

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
