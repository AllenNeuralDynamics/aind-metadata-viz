"""Configuration module for integration tests."""

import argparse


def get_base_url():
    """Get the base URL for the tests based on command line arguments."""
    parser = argparse.ArgumentParser(description="Run integration tests")
    parser.add_argument(
        "--env",
        choices=["local", "prod"],
        default="local",
        help="Environment to test against (local or prod)",
    )

    # Parse known args to avoid conflicts when imported from other scripts
    args, _ = parser.parse_known_args()

    if args.env == "prod":
        return "https://metadata-portal.allenneuraldynamics-test.org"
    else:
        return "http://localhost:5006"


def parse_test_args():
    """Parse command line arguments for test scripts."""
    parser = argparse.ArgumentParser(description="Run integration tests")
    parser.add_argument(
        "--env",
        choices=["local", "prod"],
        default="local",
        help="Environment to test against (local or prod)",
    )

    return parser.parse_args()
