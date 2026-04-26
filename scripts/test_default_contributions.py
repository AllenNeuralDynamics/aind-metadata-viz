"""Integration script: verify the IBL default contributions are seeded and retrievable.

Usage
-----
    # against local server (default)
    python scripts/test_default_contributions.py

    # against prod
    python scripts/test_default_contributions.py --env prod

The script:
  1. GETs the ibl-2025 project — confirms it was seeded on server startup
  2. Prints each contributor name, affiliation, and roles
  3. Asserts key facts about the data
"""

import json
import sys

import requests

from test_config import parse_test_args

args = parse_test_args()
BASE_URL = (
    "https://metadata-portal.allenneuraldynamics-test.org"
    if args.env == "prod"
    else "http://localhost:5006"
)

PROJECT = "ibl-2025"

print(f"Testing against: {BASE_URL}")
print("=" * 60)


def sep(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def check(response: requests.Response, expected_status: int) -> dict:
    if response.status_code != expected_status:
        print(f"  FAIL  status={response.status_code}  body={response.text[:400]}")
        sys.exit(1)
    print(f"  OK    status={response.status_code}")
    try:
        return response.json()
    except Exception:
        return {}


sep(f"GET default project: {PROJECT}")
r = requests.get(f"{BASE_URL}/contributions/get?project={PROJECT}")
data = check(r, 200)

sep("Contributors")
contributors = data.get("contributors", [])
for c in contributors:
    author = c["author"]
    roles = [f"{r['role']}:{r['level']}" for r in c.get("credit_levels", [])]
    print(f"  {author['name']} ({author['affiliation']})")
    for role in roles:
        print(f"    {role}")

sep("Assertions")
names = [c["author"]["name"] for c in contributors]
assert len(contributors) == 14, f"Expected 14 contributors, got {len(contributors)}"
print("  contributor count: 14 ✓")

assert "Hannah M Bayer" in names
print("  Hannah M Bayer present ✓")

assert "Olivier Winter" in names
print("  Olivier Winter present ✓")

hb = next(c for c in contributors if c["author"]["name"] == "Hannah M Bayer")
assert hb["author"]["affiliation"] == "Columbia University, USA"
print("  Hannah M Bayer affiliation correct ✓")

hb_roles = {r["role"] for r in hb["credit_levels"]}
assert "writing-original-draft" in hb_roles
assert "conceptualization" in hb_roles
print("  Hannah M Bayer roles correct ✓")

all_levels = {r["level"] for c in contributors for r in c.get("credit_levels", [])}
assert all_levels <= {"equal", "supporting"}, f"Unexpected levels: {all_levels - {'equal', 'supporting'}}"
print("  only equal/supporting levels used ✓")

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
