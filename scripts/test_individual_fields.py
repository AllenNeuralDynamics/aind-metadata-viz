import requests
import json
import os

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
# Construct path to resources folder (in the same directory as this script)
resources_path = os.path.join(script_dir, "resources", "metadata.json")

# Load the full metadata
with open(resources_path, "r") as f:
    metadata = json.load(f)

# List of fields to test individually with their corresponding endpoints
fields_to_test = [
    ("subject", "/validate/subject"),
    ("data_description", "/validate/data_description"),
    ("procedures", "/validate/procedures"),
    ("instrument", "/validate/instrument"),
    ("processing", "/validate/processing"),
    ("acquisition", "/validate/acquisition"),
    ("quality_control", "/validate/quality_control"),
]


def test_endpoint(field_name, field_data, endpoint_url, test_type):
    """Test a single endpoint with field data"""
    print(f"  {test_type}: ", end="")

    response = requests.post(endpoint_url, json=field_data)

    try:
        response_json = response.json()
        if response.status_code == 200:
            print("✅ VALID")
            return True
        else:
            print("❌ INVALID")
            print(f"    Status: {response.status_code}")
            print(f"    Error: {response_json.get('details', response_json.get('error', 'No details'))}")
            return False
    except json.JSONDecodeError:
        print("❌ Invalid JSON response")
        print(f"    Status: {response.status_code}")
        print(f"    Raw response: {response.text}")
        return False


print("Testing individual metadata fields:")
print("=" * 60)

for field_name, individual_endpoint in fields_to_test:
    if field_name in metadata:
        print(f"\n--- Testing {field_name} ---")

        field_data = metadata[field_name]

        # Test 1: General metadata endpoint (should pass - object_type is in field data)
        general_result = test_endpoint(
            field_name,
            field_data,
            "http://localhost:5006/validate/metadata",
            "General endpoint"
        )

        # Test 2: Individual endpoint (should pass - doesn't need object_type)
        individual_result = test_endpoint(
            field_name,
            field_data,
            f"http://localhost:5006{individual_endpoint}",
            "Individual endpoint"
        )

        # Test 3: General metadata endpoint with wrong object_type (should fail)
        field_data_wrong_type = field_data.copy()
        field_data_wrong_type["object_type"] = "Wrong Type"

        wrong_type_result = test_endpoint(
            field_name,
            field_data_wrong_type,
            "http://localhost:5006/validate/metadata",
            "General endpoint (wrong object_type)"
        )

        # Test 4: General metadata endpoint without object_type (should fail)
        field_data_no_type = field_data.copy()
        if "object_type" in field_data_no_type:
            del field_data_no_type["object_type"]

        no_type_result = test_endpoint(
            field_name,
            field_data_no_type,
            "http://localhost:5006/validate/metadata",
            "General endpoint (no object_type)"
        )

        # Summary
        if general_result and individual_result and not wrong_type_result and not no_type_result:
            print(f"  📋 Summary: {field_name} validation working correctly")
        else:
            print(f"  ⚠️  Summary: {field_name} has validation issues")
            print("    Expected: general=✅, individual=✅, wrong_type=❌, no_type=❌")
            general_icon = '✅' if general_result else '❌'
            individual_icon = '✅' if individual_result else '❌'
            wrong_type_icon = '✅' if wrong_type_result else '❌'
            no_type_icon = '✅' if no_type_result else '❌'
            print(f"    Actual: general={general_icon}, individual={individual_icon}, "
                  f"wrong_type={wrong_type_icon}, no_type={no_type_icon}")
    else:
        print(f"\n--- {field_name} NOT FOUND in metadata ---")

print("\n" + "=" * 60)
print("Individual field testing complete!")
print("✨ Tested both general /validate/metadata and individual endpoints")
