"""Test validation handlers including the GatherHandler."""

import json
import unittest
from unittest.mock import Mock, patch
import os
from fastapi.testclient import TestClient

from aind_metadata_viz.main import app


client = TestClient(app)


def load_test_response(filename):
    test_dir = os.path.dirname(__file__)
    file_path = os.path.join(test_dir, "resources", "metadata_service", filename)
    with open(file_path, "r") as f:
        return json.load(f)


class TestGatherHandler(unittest.TestCase):

    def setUp(self):
        self.subject_response = load_test_response("subject_response.json")
        self.procedures_response = load_test_response("procedures_response.json")
        self.funding_response = load_test_response("funding_response.json")

    @patch("requests.get")
    def test_gather_success(self, mock_get):
        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200
            if "/subject/" in url:
                mock_response.json.return_value = {"data": self.subject_response}
            elif "/procedures/" in url:
                mock_response.json.return_value = {"data": self.procedures_response}
            elif "/funding/" in url:
                mock_response.json.return_value = self.funding_response
            else:
                mock_response.status_code = 404
            return mock_response

        mock_get.side_effect = mock_requests_side_effect

        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
            "tags": ["test", "validation"],
            "data_summary": "Test data gathering",
        }

        response = client.post("/gather", json=test_data)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()

        self.assertIn("subject", response_data)
        self.assertIn("procedures", response_data)
        self.assertIn("data_description", response_data)
        self.assertEqual(response_data["subject"]["subject_id"], "804670")
        self.assertEqual(response_data["procedures"]["subject_id"], "804670")

        data_desc = response_data["data_description"]
        self.assertEqual(data_desc["subject_id"], "804670")
        self.assertEqual(data_desc["project_name"], "test-project")
        modality_abbrevs = [
            m["abbreviation"] if isinstance(m, dict) else m
            for m in data_desc["modalities"]
        ]
        self.assertIn("ecephys", modality_abbrevs)
        self.assertEqual(data_desc["tags"], ["test", "validation"])
        self.assertEqual(data_desc["data_summary"], "Test data gathering")

    def test_gather_missing_subject_id(self):
        response = client.post("/gather", json={"project_name": "test-project"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("subject_id is required", response.json()["error"])

    def test_gather_missing_project_name(self):
        response = client.post("/gather", json={"subject_id": "804670"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("project_name is required", response.json()["error"])

    def test_gather_invalid_json(self):
        response = client.post(
            "/gather",
            content=b"invalid json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid JSON format", response.json()["error"])

    @patch("requests.get")
    def test_gather_subject_not_found(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        test_data = {
            "subject_id": "nonexistent",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
        }

        response = client.post("/gather", json=test_data)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Subject metadata not found", response.json()["details"])

    @patch("requests.get")
    def test_gather_service_error(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
        }

        response = client.post("/gather", json=test_data)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to gather metadata", response.json()["error"])

    @patch("requests.get")
    def test_gather_with_custom_service_url(self, mock_get):
        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200
            self.assertIn("custom-service.com", url)
            if "/subject/" in url:
                mock_response.json.return_value = {"data": self.subject_response}
            elif "/procedures/" in url:
                mock_response.json.return_value = {"data": self.procedures_response}
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

        response = client.post("/gather", json=test_data)
        self.assertEqual(response.status_code, 200)

    @patch("requests.get")
    def test_gather_validation_error(self, mock_get):
        invalid_subject = {"object_type": "Subject", "subject_id": "804670"}

        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200
            if "/subject/" in url:
                mock_response.json.return_value = {"data": invalid_subject}
            elif "/procedures/" in url:
                mock_response.json.return_value = {"data": self.procedures_response}
            elif "/funding/" in url:
                mock_response.json.return_value = self.funding_response
            return mock_response

        mock_get.side_effect = mock_requests_side_effect

        test_data = {
            "subject_id": "804670",
            "project_name": "test-project",
            "modalities": ["ECEPHYS"],
        }

        response = client.post("/gather", json=test_data)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Subject validation failed", response.json()["details"])

    @patch("requests.get")
    def test_gather_with_all_optional_params(self, mock_get):
        def mock_requests_side_effect(url):
            mock_response = Mock()
            mock_response.status_code = 200
            if "/subject/" in url:
                mock_response.json.return_value = {"data": self.subject_response}
            elif "/procedures/" in url:
                mock_response.json.return_value = {"data": self.procedures_response}
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

        response = client.post("/gather", json=test_data)
        self.assertEqual(response.status_code, 200)
        data_desc = response.json()["data_description"]
        self.assertEqual(data_desc["tags"], ["test", "comprehensive"])
        self.assertEqual(data_desc["restrictions"], "Internal use only")
        self.assertEqual(data_desc["data_summary"], "Comprehensive test with all options")
        modality_abbrevs = [
            m["abbreviation"] if isinstance(m, dict) else m
            for m in data_desc["modalities"]
        ]
        self.assertIn("ecephys", modality_abbrevs)
        self.assertIn("behavior", modality_abbrevs)


class TestUploadMetadataHandler(unittest.TestCase):

    def test_validate_valid_metadata(self):
        valid_metadata = {
            "object_type": "Subject",
            "subject_id": "test123",
            "subject_details": {
                "object_type": "Mouse subject",
                "sex": "Male",
                "date_of_birth": "2023-01-01",
                "genotype": "wt",
                "strain": {"name": "C57BL/6J"},
                "species": {
                    "name": "Mus musculus",
                    "registry": "National Center for Biotechnology Information (NCBI)",
                    "registry_identifier": "NCBI:txid10090",
                },
            },
        }

        response = client.post("/validate/metadata", json=valid_metadata)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "valid")

    def test_validate_invalid_object_type(self):
        response = client.post(
            "/validate/metadata",
            json={"object_type": "InvalidType", "some_data": "test"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown or missing object_type", response.json()["error"])

    def test_validate_missing_object_type(self):
        response = client.post("/validate/metadata", json={"some_data": "test"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown or missing object_type", response.json()["error"])


class TestValidateFilesHandler(unittest.TestCase):

    def test_validate_files_valid(self):
        valid_files_data = {
            "data_description": {
                "name": "test-dataset",
                "object_type": "Data description",
                "creation_time": "2023-01-01T12:00:00+00:00",
                "institution": {"abbreviation": "AIND", "name": "Allen Institute for Neural Dynamics"},
                "data_level": "raw",
                "modalities": [{"abbreviation": "ecephys", "name": "Extracellular electrophysiology"}],
                "funding_source": [{"funder": {"abbreviation": "AIND", "name": "Allen Institute for Neural Dynamics"}}],
                "investigators": [{"name": "Test User"}],
                "project_name": "test-project",
                "subject_id": "test123",
            },
        }

        response = client.post("/validate/files", json=valid_files_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "valid")

    def test_validate_files_missing_data_description(self):
        response = client.post(
            "/validate/files",
            json={"subject": {"object_type": "Subject", "subject_id": "test123"}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("data_description field is required", response.json()["error"])

    def test_validate_files_missing_name(self):
        response = client.post(
            "/validate/files",
            json={
                "data_description": {
                    "object_type": "Data description",
                    "creation_time": "2023-01-01T12:00:00+00:00",
                }
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "data_description.name field is required", response.json()["error"]
        )


class TestUpgradeEndpoint(unittest.TestCase):

    def _minimal_subject(self):
        return {
            "object_type": "Subject",
            "subject_id": "12345",
            "sex": "Male",
            "date_of_birth": "2023-01-01",
            "species": {
                "name": "Mus musculus",
                "registry": "National Center for Biotechnology Information (NCBI)",
                "registry_identifier": "NCBI:txid10090",
            },
            "genotype": "wt",
        }

    def test_upgrade_with_body(self):
        payload = {"subject": self._minimal_subject()}
        response = client.post("/upgrade", json=payload)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("files_tested", body)
        self.assertIn("subject", body["files_tested"])

    def test_upgrade_invalid_json(self):
        response = client.post(
            "/upgrade",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid JSON format", response.json()["error"])

    def test_upgrade_no_core_fields(self):
        response = client.post("/upgrade", json={"foo": "bar"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("No recognized metadata fields", response.json()["error"])

    @patch("aind_metadata_viz.endpoints.retrieve_records")
    def test_upgrade_by_asset_name(self, mock_retrieve):
        mock_result = Mock()
        mock_result.records = [{"name": "test-asset", "subject": self._minimal_subject()}]
        mock_retrieve.return_value = mock_result

        response = client.post("/upgrade?asset_name=test-asset")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("files_tested", body)
        mock_retrieve.assert_called_once_with({"name": "test-asset"}, limit=1)

    @patch("aind_metadata_viz.endpoints.retrieve_records")
    def test_upgrade_by_asset_name_not_found(self, mock_retrieve):
        mock_result = Mock()
        mock_result.records = []
        mock_retrieve.return_value = mock_result

        response = client.post("/upgrade?asset_name=nonexistent")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["error"])

    @patch("aind_metadata_viz.endpoints.retrieve_records")
    def test_upgrade_by_asset_name_fetch_error(self, mock_retrieve):
        mock_retrieve.side_effect = Exception("connection error")

        response = client.post("/upgrade?asset_name=test-asset")
        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to fetch record", response.json()["error"])


if __name__ == "__main__":
    unittest.main()
