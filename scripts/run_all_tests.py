#!/usr/bin/env python3
"""
Unified test runner for integration tests.

This script runs all integration tests in the scripts directory:
- test_200.py: Tests valid metadata (expects 200 response)
- test_400.py: Tests invalid metadata (expects 400 response)
- test_individual_fields.py: Tests individual field validation endpoints

Usage:
    python run_all_tests.py --env local    # Test against localhost:5006
    python run_all_tests.py --env prod     # Test against production deployment
"""

import subprocess
import sys
import os
from test_config import parse_test_args


def run_test_script(script_name, env):
    """Run a single test script with the specified environment."""
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    
    print(f"\n{'='*80}")
    print(f"Running {script_name}")
    print(f"{'='*80}")
    
    try:
        # Run the script with the same environment argument
        result = subprocess.run([
            sys.executable, script_path, '--env', env
        ], capture_output=False, text=True, check=False)
        
        if result.returncode == 0:
            print(f"✅ {script_name} passed")
            return True
        else:
            print(f"❌ {script_name} failed with exit code {result.returncode}")
            return False
            
    except Exception as e:
        print(f"❌ Error running {script_name}: {e}")
        return False


def main():
    """Main function to run all integration tests."""
    args = parse_test_args()
    
    print("🚀 Running All Integration Tests")
    print(f"Environment: {'Production' if args.env == 'prod' else 'Local'}")
    
    target_url = ('https://metadata-portal.allenneuraldynamics-test.org'
                  if args.env == 'prod' else 'http://localhost:5006')
    print(f"Target URL: {target_url}")
    
    # List of test scripts to run
    test_scripts = [
        'test_200.py',
        'test_400.py',
        'test_individual_fields.py'
    ]
    
    results = []
    
    # Run each test script
    for script in test_scripts:
        success = run_test_script(script, args.env)
        results.append((script, success))
    
    # Print summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")
    
    passed = 0
    failed = 0
    
    for script, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{script:<30} {status}")
        if success:
            passed += 1
        else:
            failed += 1
    
    print(f"\nTotal: {len(results)} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed == 0:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n💥 {failed} test(s) failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
