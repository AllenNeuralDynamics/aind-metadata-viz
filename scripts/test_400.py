import requests
from test_config import parse_test_args

# Parse command line arguments
args = parse_test_args()
base_url = 'https://metadata-portal.allenneuraldynamics-test.org' if args.env == 'prod' else 'http://localhost:5006'

print(f"Testing against: {base_url}")
print("=" * 50)

response = requests.post(
    f"{base_url}/validate/metadata", json={"test": "test"}
)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
