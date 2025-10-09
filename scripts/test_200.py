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

print(f"Testing against: {base_url}")
print("=" * 50)

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
metadata_path = os.path.join(script_dir, "resources", "metadata.json")

# Load the valid metadata from the JSON file
with open(metadata_path, "r") as f:
    metadata = json.load(f)

# Send the valid metadata to the validation endpoint
response = requests.post(f"{base_url}/validate/metadata", json=metadata)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")

# Try to parse the response as JSON to see the structure
try:
    response_json = response.json()
    print(f"Parsed JSON response: {response_json}")
except json.JSONDecodeError:
    print("Response is not valid JSON")
