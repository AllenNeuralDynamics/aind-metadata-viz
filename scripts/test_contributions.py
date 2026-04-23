"""Integration script: exercise the /contributions/post and /contributions/get endpoints.

Usage
-----
    # against local server (default)
    python scripts/test_contributions.py

    # against prod
    python scripts/test_contributions.py --env prod

The script:
  1. POSTs an initial set of contributions (YAML body)
  2. Prints the CSV file on disk so you can inspect it
  3. POSTs an updated set (JSON body, one extra contributor)
  4. Prints the updated CSV file
  5. GETs HEAD  — pretty-prints the JSON response
  6. GETs the first commit by hash — confirms old data is intact
  7. GETs with a bad project name — expects 404
"""

import json
import os
import sys
import textwrap
from pathlib import Path

import requests

from test_config import parse_test_args

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

args = parse_test_args()
BASE_URL = (
    "https://metadata-portal.allenneuraldynamics-test.org"
    if args.env == "prod"
    else "http://localhost:5006"
)

PROJECT = "test-contributions-script"
STORE_DIR = Path.home() / ".aind_contributions"
CSV_FILE = STORE_DIR / f"{PROJECT}.csv"

print(f"Testing against: {BASE_URL}")
print("=" * 60)


def sep(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def print_csv() -> None:
    if CSV_FILE.exists():
        print(CSV_FILE.read_text())
    else:
        print(f"  (CSV not found at {CSV_FILE})")


def check(response: requests.Response, expected_status: int) -> dict:
    if response.status_code != expected_status:
        print(f"  FAIL  status={response.status_code}  body={response.text[:400]}")
        sys.exit(1)
    print(f"  OK    status={response.status_code}")
    try:
        return response.json()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Step 1: POST initial data as YAML
# ---------------------------------------------------------------------------

YAML_BODY = textwrap.dedent("""\
    version: 1
    project:
      name: test-contributions-script
      contributors:
        - name: Alice Nguyen
          orcid: 0000-0001-2345-6789
          credit_levels:
            - role: conceptualization
              level: lead
            - role: software
              level: lead
            - role: writing-original-draft
              level: supporting
        - name: Bob Okafor
          orcid: 0000-0002-3456-7890
          credit_levels:
            - role: data-curation
              level: equal
            - role: validation
              level: equal
""")

sep("POST v1 (YAML body)")
r = requests.post(
    f"{BASE_URL}/contributions/post?project={PROJECT}&message=initial+version",
    data=YAML_BODY.encode("utf-8"),
    headers={"Content-Type": "text/plain"},
)
v1 = check(r, 200)
commit_v1 = v1.get("commit", "")
print(f"  commit v1: {commit_v1[:12]}")

sep("CSV after v1")
print_csv()

# ---------------------------------------------------------------------------
# Step 2: POST updated data as JSON (add a third contributor)
# ---------------------------------------------------------------------------

JSON_BODY = {
    "project_name": PROJECT,
    "contributors": [
        {
            "person": {
                "name": "Alice Nguyen",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0001-2345-6789",
            },
            "credit_levels": [
                {"role": "conceptualization", "level": "lead"},
                {"role": "software", "level": "lead"},
                {"role": "writing-original-draft", "level": "lead"},  # upgraded
            ],
        },
        {
            "person": {
                "name": "Bob Okafor",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0002-3456-7890",
            },
            "credit_levels": [
                {"role": "data-curation", "level": "equal"},
                {"role": "validation", "level": "equal"},
            ],
        },
        {
            "person": {
                "name": "Carmen Silva",
                "registry": "Open Researcher and Contributor ID (ORCID)",
                "registry_identifier": "0000-0003-4567-8901",
            },
            "credit_levels": [
                {"role": "visualization", "level": "lead"},
                {"role": "writing-review-editing", "level": "supporting"},
            ],
        },
    ],
}

sep("POST v2 (JSON body, 3 contributors)")
r = requests.post(
    f"{BASE_URL}/contributions/post?project={PROJECT}&message=add+carmen",
    data=json.dumps(JSON_BODY).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
v2 = check(r, 200)
commit_v2 = v2.get("commit", "")
print(f"  commit v2: {commit_v2[:12]}")

sep("CSV after v2")
print_csv()

# ---------------------------------------------------------------------------
# Step 3: GET HEAD
# ---------------------------------------------------------------------------

sep("GET HEAD (latest)")
r = requests.get(f"{BASE_URL}/contributions/get?project={PROJECT}")
data = check(r, 200)
print(json.dumps(data, indent=2))

# ---------------------------------------------------------------------------
# Step 4: GET specific commit (v1)
# ---------------------------------------------------------------------------

sep(f"GET commit v1 ({commit_v1[:12]})")
r = requests.get(
    f"{BASE_URL}/contributions/get?project={PROJECT}&commit={commit_v1}"
)
data = check(r, 200)
names_v1 = [c["person"]["name"] for c in data.get("contributors", [])]
print(f"  contributors in v1: {names_v1}")
assert len(names_v1) == 2, f"Expected 2 contributors in v1, got {len(names_v1)}"
print("  assertion passed: v1 has 2 contributors")

# ---------------------------------------------------------------------------
# Step 5: GET unknown project → 404
# ---------------------------------------------------------------------------

sep("GET unknown project (expect 404)")
r = requests.get(f"{BASE_URL}/contributions/get?project=no-such-project-xyz")
check(r, 404)

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
