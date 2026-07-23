"""Integration smoke test for contributions endpoints (unauthenticated).

Passwords and scoped tokens have been removed. Write access is now governed by
ORCID session (admins edit anything; anyone else may only add/edit their own
row) plus the admin ``edit_locked`` flag, and **creating a new project requires
an ORCID login**. Because this script runs without a session cookie, it can only
exercise the endpoints' unauthenticated behavior:

1.  POST  — anonymous create of a new project → expect 401 (login required)
2.  GET   — unknown project → expect 404
3.  GET   — missing project/doi param → expect 400
4.  GET   author-image without author param → expect 400
5.  GET   author-image for unknown author → expect 404
6.  GET   author-image for a known author with an image → expect 200

The authenticated flows (admin edits, anonymous "add your own row" to an
existing project, edit_locked enforcement) require an ORCID session and are
covered by the unit tests in ``tests/test_contributions.py``.

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


# ---------------------------------------------------------------------------
# Step 1: anonymous create of a new project → 401 (login required)
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
            "credit_levels": [{"role": "conceptualization", "level": "lead"}],
        }
    ],
}

sep("Step 1: POST anonymous create of a new project (expect 401)")
check(
    requests.post(
        f"{POST_URL}?project={PROJECT}&message=initial+version",
        data=json.dumps(V1).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    ),
    401,
)

# ---------------------------------------------------------------------------
# Step 2: GET unknown project → 404
# ---------------------------------------------------------------------------

sep("Step 2: GET unknown project (expect 404)")
check(requests.get(GET_URL, params={"project": PROJECT}), 404)

# ---------------------------------------------------------------------------
# Step 3: GET without project/doi param → 400
# ---------------------------------------------------------------------------

sep("Step 3: GET without project or doi (expect 400)")
check(requests.get(GET_URL), 400)

# ---------------------------------------------------------------------------
# Step 4: author-image — missing param → 400
# ---------------------------------------------------------------------------

sep("Step 4: GET author-image without author param (expect 400)")
check(requests.get(AUTHOR_IMAGE_URL), 400)

# ---------------------------------------------------------------------------
# Step 5: author-image — unknown author → 404
# ---------------------------------------------------------------------------

sep("Step 5: GET author-image for unknown author (expect 404)")
check(requests.get(AUTHOR_IMAGE_URL, params={"author": "Totally Made Up Person XYZ"}), 404)

# ---------------------------------------------------------------------------
# Step 6: author-image — known author with image → 200
# ---------------------------------------------------------------------------

sep("Step 6: GET author-image for known author with image (expect 200)")
data = check(requests.get(AUTHOR_IMAGE_URL, params={"author": "Daniel Birman"}), 200)
assert data.get("author") == "Daniel Birman", f"unexpected author: {data}"
assert "image_key" in data, f"missing image_key in response: {data}"
assert data["image_key"].startswith("contributions-app/images/"), f"unexpected key: {data}"
print(f"  image_key: {data['image_key']}")

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
