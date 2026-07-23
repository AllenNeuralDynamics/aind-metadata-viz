"""Smoke tests for FastAPI's auto-generated docs (/docs, /redoc, /openapi.json).

These are the actual regression guard for "typing routes made /docs useful" —
they assert real parameter/body schemas show up for newly-typed routes, not
just that the route exists.
"""

import unittest

from fastapi.testclient import TestClient

from aind_metadata_viz.main import app

client = TestClient(app)


class TestDocsEndpointsReachable(unittest.TestCase):
    def test_docs_returns_200(self):
        response = client.get("/docs")
        self.assertEqual(response.status_code, 200)

    def test_redoc_returns_200(self):
        response = client.get("/redoc")
        self.assertEqual(response.status_code, 200)

    def test_openapi_json_returns_200(self):
        response = client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("paths", response.json())


class TestOpenApiSchemaContent(unittest.TestCase):
    def setUp(self):
        self.schema = client.get("/openapi.json").json()

    def _params(self, path, method):
        operation = self.schema["paths"][path][method]
        return {p["name"]: p for p in operation.get("parameters", [])}

    def test_scheduled_acquisitions_get_documents_include_past(self):
        params = self._params("/scheduled-acquisitions", "get")
        self.assertIn("include_past", params)
        self.assertEqual(params["include_past"]["schema"]["type"], "boolean")

    def test_acquisition_types_post_documents_request_body(self):
        operation = self.schema["paths"]["/acquisition-types"]["post"]
        self.assertIn("requestBody", operation)

    def test_contributions_get_documents_query_params(self):
        params = self._params("/contributions/get", "get")
        for name in ("project", "doi", "history", "commit", "format"):
            self.assertIn(name, params)

    def test_routes_are_tagged(self):
        gather_tags = self.schema["paths"]["/gather"]["post"]["tags"]
        self.assertIn("gather", gather_tags)
        acquisitions_tags = self.schema["paths"]["/acquisition-types"]["get"]["tags"]
        self.assertIn("acquisitions", acquisitions_tags)
        contributions_tags = self.schema["paths"]["/contributions/get"]["get"]["tags"]
        self.assertIn("contributions", contributions_tags)


if __name__ == "__main__":
    unittest.main()
