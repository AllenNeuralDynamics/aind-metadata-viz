"""Integration script: verify the np-opto default contributions are seeded and retrievable.

Usage
-----
    # against local server (default)
    python scripts/test_default_contributions.py

    # against prod
    python scripts/test_default_contributions.py --env prod

The script:
  1. GETs the np-opto project — confirms it was seeded on server startup
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

PROJECT = "np-opto"

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
assert len(contributors) == 27, f"Expected 27 contributors, got {len(contributors)}"
print("  contributor count: 27 ✓")

assert "Anna Lakunina" in names
print("  Anna Lakunina present ✓")

assert "Matteo Carandini" in names
print("  Matteo Carandini present ✓")

al = next(c for c in contributors if c["author"]["name"] == "Anna Lakunina")
assert "Allen Institute for Neural Dynamics, Seattle, WA, USA" in al["author"]["affiliation"]
print("  Anna Lakunina affiliation correct ✓")

doi = data.get("doi")
assert doi == "https://doi.org/10.1101/2025.02.04.636286", f"Unexpected DOI: {doi}"
print("  DOI correct ✓")

assets = data.get("assets", [])
assert len(assets) == 50, f"Expected 50 assets, got {len(assets)}"
print("  asset count: 50 ✓")

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
