"""Test validation handlers including the GatherHandler."""

import json
import unittest
from unittest.mock import Mock, patch
import os
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from aind_metadata_viz.validation import ROUTES


def fetch_helper(test_case, url, method="POST", body=None, headers=None):
    """Helper function to make fetch calls with consistent formatting"""
    if headers is None:
        headers = {"Content-Type": "application/json"}
    return test_case.fetch(url, method=method, body=body, headers=headers)


class ValidationHandlerTestCase(AsyncHTTPTestCase):
    """Base test case for validation handlers"""

    def get_app(self):
        """Create tornado application for testing"""
        return Application(ROUTES)

    def load_test_response(self, filename):
        """Load test response from resources folder"""
        test_dir = os.path.dirname(__file__)
        file_path = os.path.join(
            test_dir, "resources", "metadata_service", filename
        )
        with open(file_path, "r") as f:
            return json.load(f)


class TestGatherHandler(ValidationHandlerTestCase):
    """Test the GatherHandler endpoint"""

    def setUp(self):
        super().setUp()
        self.subject_response = self.load_test_response(
            "subject_response.json"
        )
        self.procedures_response = self.load_test_response(
            "procedures_response.json"
        )
        self.funding_response = self.load_test_response(
            "funding_response.json"
        )

    @patch("requests.get")
    def test_gather_success(self, mock_get):
        """Test successful metadata gathering"""

        # Mock the requests.get calls
        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200

            if "/subject/" in url:
                mock_response.json.return_value = {
                    "data": self.subject_response
                }
            elif "/procedures/" in url:
                mock_response.json.return_value = {
                    "data": self.procedures_response
                }
            elif "/funding/" in url:
                mock_response.json.return_value = self.funding_response
            else:
                mock_response.status_code = 404

            return mock_response

        mock_get.side_effect = mock_requests_side_effect

        # Test data
        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
            "tags": ["test", "validation"],
            "data_summary": "Test data gathering",
        }

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 200)
        response_data = json.loads(response.body)

        # Check that all expected fields are present
        self.assertIn("subject", response_data)
        self.assertIn("procedures", response_data)
        self.assertIn("data_description", response_data)

        # Check subject data
        self.assertEqual(response_data["subject"]["subject_id"], "804670")

        # Check procedures data
        self.assertEqual(response_data["procedures"]["subject_id"], "804670")

        # Check data description
        data_desc = response_data["data_description"]
        self.assertEqual(data_desc["subject_id"], "804670")
        self.assertEqual(data_desc["project_name"], "test-project")
        # Check modalities are present (they will be objects with abbreviation)
        modality_abbrevs = [
            m["abbreviation"] if isinstance(m, dict) else m
            for m in data_desc["modalities"]
        ]
        self.assertIn("ecephys", modality_abbrevs)
        self.assertEqual(data_desc["tags"], ["test", "validation"])
        self.assertEqual(data_desc["data_summary"], "Test data gathering")

    def test_gather_missing_subject_id(self):
        """Test gather with missing subject_id"""
        test_data = {"project_name": "test-project"}

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 400)
        response_data = json.loads(response.body)
        self.assertIn("subject_id is required", response_data["error"])

    def test_gather_missing_project_name(self):
        """Test gather with missing project_name"""
        test_data = {"subject_id": "804670"}

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 400)
        response_data = json.loads(response.body)
        self.assertIn("project_name is required", response_data["error"])

    def test_gather_invalid_json(self):
        """Test gather with invalid JSON"""
        response = self.fetch(
            "/gather",
            method="POST",
            body="invalid json",
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 400)
        response_data = json.loads(response.body)
        self.assertIn("Invalid JSON format", response_data["error"])

    @patch("requests.get")
    def test_gather_subject_not_found(self, mock_get):
        """Test gather when subject is not found"""
        # Mock 404 response for subject
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        test_data = {
            "subject_id": "nonexistent",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
        }

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        # Should fail when subject is not found (required)
        self.assertEqual(response.code, 500)
        response_data = json.loads(response.body)
        self.assertIn("Subject metadata not found", response_data["details"])

    @patch("requests.get")
    def test_gather_service_error(self, mock_get):
        """Test gather when service returns error"""
        # Mock 500 response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
        }

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 500)
        response_data = json.loads(response.body)
        self.assertIn("Failed to gather metadata", response_data["error"])

    @patch("requests.get")
    def test_gather_with_custom_service_url(self, mock_get):
        """Test gather with custom metadata service URL"""

        # Mock successful responses
        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200

            # Verify custom URL is used
            self.assertIn("custom-service.com", url)

            if "/subject/" in url:
                mock_response.json.return_value = {
                    "data": self.subject_response
                }
            elif "/procedures/" in url:
                mock_response.json.return_value = {
                    "data": self.procedures_response
                }
            elif "/funding/" in url:
                mock_response.json.return_value = self.funding_response

            return mock_response

        mock_get.side_effect = mock_requests_side_effect

        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "metadata_service_url": "https://custom-service.com",
            "modalities": ["ECEPHYS"],
        }

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 200)

    @patch("requests.get")
    def test_gather_validation_error(self, mock_get):
        """Test gather with invalid metadata that fails validation"""
        # Mock responses with invalid data
        invalid_subject = {
            "object_type": "Subject",
            "subject_id": "804670",
            # Missing required fields to cause validation error
        }

        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200

            if "/subject/" in url:
                mock_response.json.return_value = {"data": invalid_subject}
            elif "/procedures/" in url:
                mock_response.json.return_value = {
                    "data": self.procedures_response
                }
            elif "/funding/" in url:
                mock_response.json.return_value = self.funding_response

            return mock_response

        mock_get.side_effect = mock_requests_side_effect

        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
        }

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 500)
        response_data = json.loads(response.body)
        self.assertIn("Subject validation failed", response_data["details"])

    @patch("requests.get")
    def test_gather_with_all_optional_params(self, mock_get):
        """Test gather with all optional parameters"""

        # Mock successful responses
        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200

            if "/subject/" in url:
                mock_response.json.return_value = {
                    "data": self.subject_response
                }
            elif "/procedures/" in url:
                mock_response.json.return_value = {
                    "data": self.procedures_response
                }
            elif "/funding/" in url:
                mock_response.json.return_value = self.funding_response

            return mock_response

        mock_get.side_effect = mock_requests_side_effect

        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "metadata_service_url": "http://custom-service",
            "modalities": ["ECEPHYS", "BEHAVIOR"],
            "tags": ["test", "comprehensive"],
            "group": "behavior",
            "restrictions": "Internal use only",
            "data_summary": "Comprehensive test with all options",
        }

        response = self.fetch(
            "/gather",
            method="POST",
            body=json.dumps(test_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 200)
        response_data = json.loads(response.body)

        # Verify all optional parameters are included in data_description
        data_desc = response_data["data_description"]
        self.assertEqual(data_desc["tags"], ["test", "comprehensive"])
        self.assertEqual(data_desc["restrictions"], "Internal use only")
        self.assertEqual(
            data_desc["data_summary"], "Comprehensive test with all options"
        )
        # Check modalities are present (they will be objects with abbreviation)
        modality_abbrevs = [
            m["abbreviation"] if isinstance(m, dict) else m
            for m in data_desc["modalities"]
        ]
        self.assertIn("ecephys", modality_abbrevs)
        self.assertIn("behavior", modality_abbrevs)


class TestUploadMetadataHandler(ValidationHandlerTestCase):
    """Test the UploadMetadataHandler endpoint"""

    def test_validate_valid_metadata(self):
        """Test validation with valid metadata"""
        valid_metadata = {
            "object_type": "Subject",
            "subject_id": "test123",
            "subject_details": {
                "object_type": "Mouse subject",
                "sex": "Male",
                "date_of_birth": "2023-01-01",
                "strain": {"name": "C57BL/6J", "species": "Mus musculus"},
                "species": {
                    "name": "Mus musculus",
                    "registry": "NCBI",
                    "registry_identifier": "NCBI:txid10090",
                },
            },
        }

        response = self.fetch(
            "/validate/metadata",
            method="POST",
            body=json.dumps(valid_metadata),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 200)
        response_data = json.loads(response.body)
        self.assertEqual(response_data["status"], "valid")

    def test_validate_invalid_object_type(self):
        """Test validation with invalid object_type"""
        invalid_metadata = {"object_type": "InvalidType", "some_data": "test"}

        response = self.fetch(
            "/validate/metadata",
            method="POST",
            body=json.dumps(invalid_metadata),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 400)
        response_data = json.loads(response.body)
        self.assertIn("Unknown or missing object_type", response_data["error"])

    def test_validate_missing_object_type(self):
        """Test validation with missing object_type"""
        invalid_metadata = {"some_data": "test"}

        response = self.fetch(
            "/validate/metadata",
            method="POST",
            body=json.dumps(invalid_metadata),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 400)
        response_data = json.loads(response.body)
        self.assertIn("Unknown or missing object_type", response_data["error"])


class TestValidateFilesHandler(ValidationHandlerTestCase):
    """Test the ValidateFilesHandler endpoint"""

    def test_validate_files_valid(self):
        """Test files validation with valid data"""
        valid_files_data = {
            "data_description": {
                "name": "test-dataset",
                "object_type": "Data description",
                "creation_time": "2023-01-01T12:00:00+00:00",
                "institution": "AI",
                "data_level": "raw",
                "modalities": ["ECEPHYS"],
            },
            "subject": {"object_type": "Subject", "subject_id": "test123"},
        }

        response = self.fetch(
            "/validate/files",
            method="POST",
            body=json.dumps(valid_files_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 200)
        response_data = json.loads(response.body)
        self.assertEqual(response_data["status"], "valid")

    def test_validate_files_missing_data_description(self):
        """Test files validation with missing data_description"""
        invalid_data = {
            "subject": {"object_type": "Subject", "subject_id": "test123"}
        }

        response = self.fetch(
            "/validate/files",
            method="POST",
            body=json.dumps(invalid_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 400)
        response_data = json.loads(response.body)
        self.assertIn(
            "data_description field is required", response_data["error"]
        )

    def test_validate_files_missing_name(self):
        """Test files validation with missing name in data_description"""
        invalid_data = {
            "data_description": {
                "object_type": "Data description",
                "creation_time": "2023-01-01T12:00:00+00:00",
            }
        }

        response = self.fetch(
            "/validate/files",
            method="POST",
            body=json.dumps(invalid_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.code, 400)
        response_data = json.loads(response.body)
        self.assertIn(
            "data_description.name field is required", response_data["error"]
        )


if __name__ == "__main__":
    unittest.main()
