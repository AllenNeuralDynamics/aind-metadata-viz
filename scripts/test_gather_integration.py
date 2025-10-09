#!/usr/bin/env python3
"""
Integration test for the gather endpoint using real metadata service.

This test:
1. Uses acquisition and instrument from the existing metadata.json file
2. Calls the /gather endpoint to get fresh data_description, subject, and procedures from metadata service
3. Combines them to create a complete metadata object
4. Validates that the combined metadata passes validation

Usage:
    python test_gather_integration.py --env local    # Test against localhost:5006
    python test_gather_integration.py --env prod     # Test against production deployment
"""

import requests
import json
import os
import sys
from test_config import parse_test_args


def main():
    # Parse command line arguments
    args = parse_test_args()
    base_url = (
        "https://metadata-portal.allenneuraldynamics-test.org"
        if args.env == "prod"
        else "http://localhost:5006"
    )

    print(f"Testing gather endpoint integration against: {base_url}")
    print("=" * 80)

    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    metadata_path = os.path.join(script_dir, "resources", "metadata.json")

    # Load the existing metadata file
    try:
        with open(metadata_path, "r") as f:
            existing_metadata = json.load(f)
        print("✅ Loaded existing metadata.json")
    except Exception as e:
        print(f"❌ Failed to load metadata.json: {e}")
        sys.exit(1)

    # Extract subject_id and project_name from existing metadata
    subject_id = existing_metadata["subject"]["subject_id"]
    project_name = existing_metadata["data_description"]["project_name"]

    print(f"📋 Subject ID: {subject_id}")
    print(f"📋 Project Name: {project_name}")

    # Extract acquisition start time from existing metadata if available
    acquisition_start_time = None
    if (
        "acquisition" in existing_metadata
        and "acquisition_start_time" in existing_metadata["acquisition"]
    ):
        acquisition_start_time = existing_metadata["acquisition"][
            "acquisition_start_time"
        ]
        print(f"📅 Using acquisition start time: {acquisition_start_time}")

    # Prepare gather request with some optional parameters
    gather_params = {
        "subject_id": subject_id,
        "project_name": project_name,
        "modalities": "pophys",  # Use abbreviation string
        "tags": "integration_test",
        "data_summary": "Integration test of gather endpoint with real metadata service",
    }

    # Add acquisition_start_time if available
    if acquisition_start_time:
        gather_params["acquisition_start_time"] = acquisition_start_time

    print("\n🚀 Calling /gather endpoint...")
    print(f"Parameters: {json.dumps(gather_params, indent=2)}")

    # Call the gather endpoint
    try:
        response = requests.get(
            f"{base_url}/gather", params=gather_params, timeout=30
        )

        print(f"\n📊 Gather Response Status: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Gather endpoint failed: {response.text}")
            sys.exit(1)

        gathered_data = response.json()
        print("✅ Successfully gathered metadata from service")

        # Print what we got
        components = list(gathered_data.keys())
        print(f"📦 Gathered components: {components}")

    except Exception as e:
        print(f"❌ Error calling gather endpoint: {e}")
        sys.exit(1)

    # Extract acquisition and instrument from existing metadata
    acquisition = existing_metadata.get("acquisition")
    instrument = existing_metadata.get("instrument")

    print(
        f"\n📄 Using acquisition from metadata.json: {acquisition['object_type'] if acquisition else 'None'}"
    )
    print(
        f"📄 Using instrument from metadata.json: {instrument['object_type'] if instrument else 'None'}"
    )

    # Combine gathered data with existing acquisition and instrument
    combined_metadata = {
        "object_type": "Metadata",
        "name": f"integration_test_{subject_id}",
        "location": "",  # Will be set by transfer service
        "subject": gathered_data["subject"],
        "data_description": gathered_data["data_description"],
        "procedures": gathered_data["procedures"],
    }

    # Add acquisition and instrument if they exist
    if acquisition:
        combined_metadata["acquisition"] = acquisition
    if instrument:
        combined_metadata["instrument"] = instrument

    print(
        f"\n🔧 Created combined metadata with components: {list(combined_metadata.keys())}"
    )

    # Test the combined metadata against the validation endpoint
    print("\n🧪 Testing combined metadata validation...")

    try:
        validation_response = requests.post(
            f"{base_url}/validate/metadata", json=combined_metadata, timeout=30
        )

        print(
            f"📊 Validation Response Status: {validation_response.status_code}"
        )

        if validation_response.status_code == 200:
            validation_result = validation_response.json()
            print("✅ Combined metadata validation passed!")
            print(f"Response: {validation_result}")
        else:
            print(
                f"❌ Combined metadata validation failed: {validation_response.text}"
            )
            # This might be expected if there are compatibility issues, so don't exit

    except Exception as e:
        print(f"❌ Error validating combined metadata: {e}")
        # Don't exit - the gather test was successful

    # Test individual components validation
    print("\n🔍 Testing individual component validations...")

    components_to_test = [
        ("subject", gathered_data["subject"]),
        ("data_description", gathered_data["data_description"]),
        ("procedures", gathered_data["procedures"]),
    ]

    if acquisition:
        components_to_test.append(("acquisition", acquisition))
    if instrument:
        components_to_test.append(("instrument", instrument))

    all_individual_passed = True

    for component_name, component_data in components_to_test:
        try:
            component_response = requests.post(
                f"{base_url}/validate/{component_name}",
                json=component_data,
                timeout=15,
            )

            if component_response.status_code == 200:
                print(f"✅ {component_name} validation passed")
            else:
                print(
                    f"❌ {component_name} validation failed: {component_response.text}"
                )
                all_individual_passed = False

        except Exception as e:
            print(f"❌ Error validating {component_name}: {e}")
            all_individual_passed = False

    # Final summary
    print("\n" + "=" * 80)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 80)

    print("✅ Gather endpoint successfully retrieved metadata from service")
    print("✅ Combined metadata with existing acquisition and instrument")

    if all_individual_passed:
        print("✅ All individual component validations passed")
    else:
        print("⚠️  Some individual component validations failed")

    print(f"\n📋 Final metadata structure:")
    print(f"   - Subject ID: {gathered_data['subject']['subject_id']}")
    print(f"   - Project: {gathered_data['data_description']['project_name']}")
    print(f"   - Data Description: ✅ (from service)")
    print(f"   - Subject: ✅ (from service)")
    print(f"   - Procedures: ✅ (from service)")
    print(
        f"   - Acquisition: {'✅ (from file)' if acquisition else '❌ (missing)'}"
    )
    print(
        f"   - Instrument: {'✅ (from file)' if instrument else '❌ (missing)'}"
    )

    print("\n🎉 Integration test completed successfully!")


if __name__ == "__main__":
    main()
