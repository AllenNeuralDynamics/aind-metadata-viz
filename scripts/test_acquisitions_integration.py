"""Integration smoke test for retired metadata-portal endpoints.

Usage
-----
    python scripts/test_acquisitions_integration.py
"""

import sys

import requests

BASE_URL = "https://metadata-portal.allenneuraldynamics.org"
OPENAPI_URL = f"{BASE_URL}/openapi.json"
RETIRED_ENDPOINTS = (
    ("GET", f"{BASE_URL}/acquisition-types"),
    ("POST", f"{BASE_URL}/acquisition-types"),
    ("GET", f"{BASE_URL}/verification/graph"),
)


def check(response, expected_status):
    if response.status_code != expected_status:
        print(
            f"FAIL {response.request.method} {response.url}: "
            f"status={response.status_code} body={response.text[:400]}"
        )
        sys.exit(1)
    print(f"OK   {response.request.method} {response.url}: status={response.status_code}")


print(f"Testing against: {BASE_URL}")

openapi_response = requests.get(OPENAPI_URL, timeout=30)
check(openapi_response, 200)
paths = openapi_response.json().get("paths", {})
if "/acquisition-types" in paths:
    print("FAIL /acquisition-types is still present in OpenAPI")
    sys.exit(1)
if any(path.startswith("/verification") for path in paths):
    print("FAIL a verification path is still present in OpenAPI")
    sys.exit(1)
print("OK   retired endpoint groups are absent from OpenAPI")

for method, url in RETIRED_ENDPOINTS:
    response = requests.request(
        method,
        url,
        json={"platform": "test", "acquisition_type": "retired"} if method == "POST" else None,
        timeout=30,
    )
    check(response, 404)

print("ALL STEPS PASSED")
