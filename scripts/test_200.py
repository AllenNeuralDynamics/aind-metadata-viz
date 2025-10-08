import requests
import json

# Load the valid metadata from the JSON file
with open("scripts/resources/metadata.json", "r") as f:
    metadata = json.load(f)

# Send the valid metadata to the validation endpoint
response = requests.post(
    "http://localhost:5006/validate/metadata", json=metadata
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")

# Try to parse the response as JSON to see the structure
try:
    response_json = response.json()
    print(f"Parsed JSON response: {response_json}")
except json.JSONDecodeError:
    print("Response is not valid JSON")
