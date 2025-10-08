import requests

response = requests.post(
    "http://localhost:5006/validate/metadata", json={"test": "test"}
)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
