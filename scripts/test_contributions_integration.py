"""Integration test: contributions lifecycle against the production server.

Passwords and scoped tokens have been removed — write access is governed by
ORCID session (admins edit anything; anyone else may only add/edit their own
row) plus the admin ``edit_locked`` flag. This script exercises the parts that
need no session: the public read path and the anonymous "own row only" write
rules. Admin-only and edit_locked flows require a logged-in ORCID session cookie
and are covered by the unit tests in ``tests/test_contributions.py``.

Steps
-----
1.  POST v1  — minimal project (one contributor), anonymous
2.  GET      — verify project is readable and not edit_locked
3.  POST v2  — anonymous appends one new contributor → 200
4.  GET      — verify both contributors present
5.  POST     — anonymous modifies an existing author → 403
6.  POST     — anonymous removes an existing author → 403
7.  POST     — anonymous adds two new authors at once → 403
8+. author-image endpoint checks

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
GET_URL = f"{BASE_URL}/contributions/get"
POST_URL = f"{BASE_URL}/contributions/post"
AUTHOR_IMAGE_URL = f"{BASE_URL}/contributions/author-image"

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


def _author(name, orcid, roles=(("conceptualization", "lead"),)):
    return {
        "author": {
            "name": name,
            "registry": "Open Researcher and Contributor ID (ORCID)",
            "registry_identifier": orcid,
            "affiliation": ["Allen Institute for Neural Dynamics"],
        },
        "credit_levels": [{"role": r, "level": lvl} for r, lvl in roles],
    }


def _post(body, message):
    return requests.post(
        f"{POST_URL}?project={PROJECT}&message={message}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


ALICE = _author("Alice Nguyen", "0000-0001-2345-6789")
BOB = _author("Bob Rivera", "0000-0002-3456-7890")

# ---------------------------------------------------------------------------
# Step 1: POST v1 — minimal project, anonymous
# ---------------------------------------------------------------------------

V1 = {"project_name": PROJECT, "contributors": [ALICE]}

sep("Step 1: POST v1 (one contributor, anonymous)")
v1 = check(_post(V1, "initial+version"), 200)
print(f"  commit v1: {v1['commit'][:12]}")

# ---------------------------------------------------------------------------
# Step 2: GET — verify readable and not edit_locked
# ---------------------------------------------------------------------------

sep("Step 2: GET (public, should be 200 and not edit_locked)")
data = check(requests.get(GET_URL, params={"project": PROJECT}), 200)
assert data["project_name"] == PROJECT
assert len(data["contributors"]) == 1
assert data.get("edit_locked") is False, f"expected edit_locked=False, got {data.get('edit_locked')}"
print(f"  contributors: {[c['author']['name'] for c in data['contributors']]}")

# ---------------------------------------------------------------------------
# Step 3: POST v2 — anonymous appends exactly one new contributor → 200
# ---------------------------------------------------------------------------

V2 = {"project_name": PROJECT, "doi": DOI, "contributors": [ALICE, BOB]}

sep("Step 3: POST v2 (anonymous adds Bob — one new row, expect 200)")
check(_post(V2, "add+bob"), 200)

# ---------------------------------------------------------------------------
# Step 4: GET — verify both contributors present
# ---------------------------------------------------------------------------

sep("Step 4: GET (verify Alice and Bob present)")
data = check(requests.get(GET_URL, params={"project": PROJECT}), 200)
names = [c["author"]["name"] for c in data["contributors"]]
assert "Alice Nguyen" in names and "Bob Rivera" in names, names
print(f"  contributors: {names}")

# ---------------------------------------------------------------------------
# Step 5: POST — anonymous modifies an existing author → 403
# ---------------------------------------------------------------------------

ALICE_MODIFIED = _author(
    "Alice Nguyen", "0000-0001-2345-6789", roles=(("software", "supporting"),)
)
sep("Step 5: POST anonymous modifying Alice's row (expect 403)")
check(_post({"project_name": PROJECT, "contributors": [ALICE_MODIFIED, BOB]}, "edit+alice"), 403)

# ---------------------------------------------------------------------------
# Step 6: POST — anonymous removes an existing author → 403
# ---------------------------------------------------------------------------

sep("Step 6: POST anonymous removing Bob (expect 403)")
check(_post({"project_name": PROJECT, "contributors": [ALICE]}, "remove+bob"), 403)

# ---------------------------------------------------------------------------
# Step 7: POST — anonymous adds two new authors at once → 403
# ---------------------------------------------------------------------------

CARMEN = _author("Carmen Silva", "0000-0003-4567-8901")
DIANA = _author("Diana Osei", "0000-0004-5678-9012")
sep("Step 7: POST anonymous adding two new rows at once (expect 403)")
check(_post({"project_name": PROJECT, "contributors": [ALICE, BOB, CARMEN, DIANA]}, "add+two"), 403)

# ---------------------------------------------------------------------------
# Step 8: author-image — missing param → 400
# ---------------------------------------------------------------------------

sep("Step 8: GET author-image without author param (expect 400)")
check(requests.get(AUTHOR_IMAGE_URL), 400)

# ---------------------------------------------------------------------------
# Step 9: author-image — unknown author → 404
# ---------------------------------------------------------------------------

sep("Step 9: GET author-image for unknown author (expect 404)")
check(requests.get(AUTHOR_IMAGE_URL, params={"author": "Totally Made Up Person XYZ"}), 404)

# ---------------------------------------------------------------------------
# Step 10: author-image — known author with image → 200
# ---------------------------------------------------------------------------

sep("Step 10: GET author-image for known author with image (expect 200)")
data = check(requests.get(AUTHOR_IMAGE_URL, params={"author": "Daniel Birman"}), 200)
assert data.get("author") == "Daniel Birman", f"unexpected author: {data}"
assert "image_key" in data, f"missing image_key in response: {data}"
assert data["image_key"].startswith("contributions-app/images/"), f"unexpected key: {data}"
print(f"  image_key: {data['image_key']}")

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
