#!/usr/bin/env python3
"""
Test for the /validate/files endpoint.

This test loads the metadata.json file, removes all top-level fields that are not
core files, and sends the modified data to the /validate/files endpoint for validation.
"""

import requests
import json
import os
from test_config import parse_test_args

# Parse command line arguments
args = parse_test_args()
base_url = (
    "https://metadata-portal.allenneuraldynamics-test.org"
    if args.env == "prod"
    else "http://localhost:5006"
)

print(f"Testing /validate/files endpoint against: {base_url}")
print("=" * 50)

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
metadata_path = os.path.join(script_dir, "resources", "metadata.json")

# Load the metadata from the JSON file
with open(metadata_path, "r") as f:
    metadata = json.load(f)

print(f"Original metadata has {len(metadata)} top-level fields")

# Define the core fields that should be kept
core_fields = [
    "subject",
    "data_description",
    "instrument",
    "quality_control",
    "processing",
    "procedures",
    "acquisition",
    "model",
]

# Create a new metadata object with only core fields
files_metadata = {}
for field in core_fields:
    if field in metadata:
        files_metadata[field] = metadata[field]

print(
    f"Files metadata has {len(files_metadata)} top-level fields: {list(files_metadata.keys())}"
)

# Verify that data_description.name exists
if (
    "data_description" in files_metadata
    and "name" in files_metadata["data_description"]
):
    expected_name = files_metadata["data_description"]["name"]
    print(f"Expected name from data_description.name: {expected_name}")
else:
    print("ERROR: data_description.name field is missing!")
    exit(1)

# Send the files metadata to the validation endpoint
try:
    response = requests.post(
        f"{base_url}/validate/files", json=files_metadata, timeout=30
    )

    print(f"\nStatus: {response.status_code}")
    print(f"Response: {response.text}")

    # Try to parse the response as JSON to see the structure
    try:
        response_json = response.json()
        print(f"Parsed JSON response: {response_json}")
    except json.JSONDecodeError:
        print("Response is not valid JSON")

    # Check if the test passed
    if response.status_code == 200:
        print("\n✅ Test PASSED: Files endpoint validation succeeded")
        exit(0)
    else:
        print(
            f"\n❌ Test FAILED: Expected status 200, got {response.status_code}"
        )
        exit(1)

except requests.exceptions.RequestException as e:
    print(f"\n❌ Test FAILED: Request error: {e}")
    exit(1)
except Exception as e:
    print(f"\n❌ Test FAILED: Unexpected error: {e}")
    exit(1)
