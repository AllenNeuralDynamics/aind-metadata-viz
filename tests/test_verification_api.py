"""Tests for the verification graph's REST endpoints."""

import json
import unittest
from io import BytesIO
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aind_metadata_viz.verification import handlers, store
from aind_metadata_viz.verification.handlers import verification_router
from aind_metadata_viz.verification.jobs import queue

_app = FastAPI()
_app.include_router(verification_router)
client = TestClient(_app)

_ALICE = {"orcid": "0000-0001-2345-6789", "name": "Alice", "is_admin": False}
_ADMIN = {"orcid": "0000-0002-0000-0000", "name": "Root", "is_admin": True}


class _FakePaginator:
    """Stands in for boto3's list_objects_v2 paginator."""

    def __init__(self, objects):
        """Hold a reference to the fake bucket."""
        self._objects = objects

    def paginate(self, Bucket, Prefix="", **kwargs):
        """Yield one page of every key under *Prefix*."""
        keys = sorted(k for k in self._objects if k.startswith(Prefix))
        yield {"Contents": [{"Key": k, "Size": len(self._objects[k])} for k in keys]}


class _FakeS3:
    """An in-memory stand-in for S3."""

    def __init__(self):
        """Start with an empty bucket."""
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType=None, **kwargs):
        """Store an object."""
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):
        """Return an object or raise NoSuchKey."""
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "no"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def get_paginator(self, operation_name):
        """Return the listing paginator."""
        return _FakePaginator(self.objects)


def _patch_user(user):
    return patch("aind_metadata_viz.auth.session.get_current_user", return_value=user)


CODE_FILES = {
    "analysis.py": b"def main(d):\n    return {'holds': True}\n",
    "test_analysis.py": b"def test_x():\n    pass\n",
    "known_cases.json": b'[{"name": "c", "input": null, "expected": {"holds": true}}]',
    "environment.lock": b"pytest==8.0.0\n",
}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeS3()
        self._patch = patch.object(store, "_s3", return_value=self.fake)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        queue.reset()

    def _seed(self):
        store.put_node({"id": "ent-unit", "kind": "entity", "entity_type": "unit", "label": "Unit 1"})
        store.put_node({"id": "ent-stim", "kind": "entity", "entity_type": "stimulus", "label": "vis1"})
        store.put_node({
            "id": "rel-r", "kind": "relation", "label": "responds to",
            "signature": {"subject": ["unit"], "object": ["stimulus"]},
        })
        store.put_node({
            "id": "stmt-a", "kind": "statement", "label": "Unit 1 responds to vis1",
            "subject": "ent-unit", "relation": "rel-r", "object": "ent-stim",
            "status": "verified", "depends_on": [], "code": "code/stmt-a/",
            "value": {"p": 0.0004, "holds": True},
            "verification": {"reproducible": {"status": "passed", "run": {"result_hash": "abc"}}},
        })
        store.recompile()


class ReadEndpointTestCase(ApiTestCase):
    def test_the_graph_is_anonymous(self):
        self._seed()
        response = client.get("/verification/graph")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["nodes"]), 4)

    def test_an_empty_graph_returns_an_empty_snapshot(self):
        response = client.get("/verification/graph")
        self.assertEqual(response.json()["nodes"], [])

    def test_the_graph_can_be_filtered_by_status(self):
        self._seed()
        response = client.get("/verification/graph", params={"status": "verified"})
        ids = {n["id"] for n in response.json()["nodes"]}
        self.assertIn("stmt-a", ids)

    def test_the_graph_can_be_narrowed_to_a_root(self):
        self._seed()
        response = client.get("/verification/graph", params={"root": "ent-unit"})
        self.assertEqual([n["id"] for n in response.json()["nodes"]], ["ent-unit"])

    def test_the_manifest_lists_every_node(self):
        self._seed()
        self.assertEqual(len(client.get("/verification/manifest").json()), 4)

    def test_a_node_document_is_served_whole(self):
        self._seed()
        body = client.get("/verification/nodes/stmt-a").json()
        self.assertEqual(body["value"]["p"], 0.0004)
        self.assertEqual(body["verification"]["reproducible"]["status"], "passed")

    def test_an_unknown_node_is_404(self):
        response = client.get("/verification/nodes/nope")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_an_unsafe_node_id_is_400(self):
        # `..` is normalized away by the HTTP layer before routing; an id with a
        # character outside the S3-key-safe set is what actually reaches the store.
        self.assertEqual(client.get("/verification/nodes/bad!id").status_code, 400)

    def test_the_code_listing_reports_the_layout_gates(self):
        self._seed()
        for name, data in CODE_FILES.items():
            store.put_code_file("stmt-a", name, data)
        body = client.get("/verification/nodes/stmt-a/code").json()
        self.assertEqual(len(body["files"]), 4)
        self.assertTrue(body["gates"]["ok"])
        self.assertIsNotNone(body["code_hash"])

    def test_a_node_without_code_lists_nothing(self):
        self._seed()
        body = client.get("/verification/nodes/ent-unit/code").json()
        self.assertEqual(body["files"], [])
        self.assertIsNone(body["code_hash"])

    def test_one_code_file_is_served_as_plain_text(self):
        self._seed()
        store.put_code_file("stmt-a", "analysis.py", CODE_FILES["analysis.py"])
        response = client.get("/verification/nodes/stmt-a/code", params={"path": "analysis.py"})
        self.assertIn("def main", response.text)

    def test_an_unknown_code_file_is_404(self):
        self._seed()
        response = client.get("/verification/nodes/stmt-a/code", params={"path": "nope.py"})
        self.assertEqual(response.status_code, 404)

    def test_a_traversing_code_path_is_400(self):
        self._seed()
        response = client.get("/verification/nodes/stmt-a/code", params={"path": "../../secret"})
        self.assertEqual(response.status_code, 400)

    def test_run_history_is_served(self):
        self._seed()
        store.put_run("stmt-a", "2026-08-26T00-00-00", {"axis": "reproducible", "ran_at": "t", "passed": True})
        body = client.get("/verification/nodes/stmt-a/runs").json()
        self.assertEqual(body[0]["axis"], "reproducible")

    def test_document_history_is_served(self):
        self._seed()
        doc = store.get_node("stmt-a")
        doc["label"] = "renamed"
        store.put_node(doc)
        body = client.get("/verification/nodes/stmt-a/history").json()
        self.assertEqual(body[0]["label"], "Unit 1 responds to vis1")

    def test_a_store_failure_is_a_500_with_an_error_envelope(self):
        with patch.object(store, "get_snapshot", side_effect=RuntimeError("s3 down")):
            response = client.get("/verification/graph")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "s3 down")


class CreateNodeTestCase(ApiTestCase):
    def _post(self, body, user=_ALICE):
        with _patch_user(user):
            return client.post("/verification/nodes", json=body)

    def test_creating_a_node_requires_a_login(self):
        with _patch_user(None):
            response = client.post("/verification/nodes", json={"kind": "entity", "entity_type": "unit", "label": "x"})
        self.assertEqual(response.status_code, 401)

    def test_an_entity_is_created_with_a_generated_id(self):
        response = self._post({"kind": "entity", "entity_type": "unit", "label": "Unit 7"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], "ent-unit-unit-7")

    def test_a_relation_id_is_derived_from_its_label(self):
        response = self._post({
            "kind": "relation", "label": "responds to", "definition": "d",
            "signature": {"subject": ["unit"], "object": ["stimulus"]},
        })
        self.assertEqual(response.json()["id"], "rel-responds-to")

    def test_a_statement_enters_as_proposed_with_every_axis_unattempted(self):
        self._seed()
        response = self._post({
            "kind": "statement", "subject": "ent-unit", "relation": "rel-r", "object": "ent-stim",
        })
        body = response.json()
        self.assertEqual(body["status"], "proposed")
        self.assertTrue(body["id"].startswith("stmt-"))
        self.assertEqual(body["verification"]["robust"]["status"], "not_attempted")

    def test_the_author_is_recorded(self):
        response = self._post({"kind": "entity", "entity_type": "unit", "label": "Unit 7"})
        self.assertEqual(response.json()["provenance"]["author"], _ALICE["orcid"])

    def test_a_duplicate_id_is_409(self):
        self._seed()
        response = self._post({"kind": "entity", "id": "ent-unit", "entity_type": "unit", "label": "x"})
        self.assertEqual(response.status_code, 409)

    def test_a_triple_that_breaks_the_signature_is_400(self):
        self._seed()
        response = self._post({
            "kind": "statement", "subject": "ent-stim", "relation": "rel-r", "object": "ent-stim",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("relation accepts", response.json()["error"])

    def test_a_dangling_dependency_is_400(self):
        self._seed()
        response = self._post({
            "kind": "statement", "subject": "ent-unit", "relation": "rel-r", "object": "ent-stim",
            "depends_on": ["gone"],
        })
        self.assertEqual(response.status_code, 400)

    def test_an_unsafe_explicit_id_is_400(self):
        response = self._post({"kind": "entity", "id": "../escape", "entity_type": "unit", "label": "x"})
        self.assertEqual(response.status_code, 400)

    def test_creating_a_node_recompiles_the_snapshot(self):
        self._post({"kind": "entity", "entity_type": "unit", "label": "Unit 7"})
        self.assertEqual(len(client.get("/verification/graph").json()["nodes"]), 1)


class CodeUploadTestCase(ApiTestCase):
    def _upload(self, path, data, node_id="stmt-a", user=_ALICE):
        with _patch_user(user):
            return client.post(
                f"/verification/nodes/{node_id}/code", params={"path": path}, content=data
            )

    def test_uploading_requires_a_login(self):
        self._seed()
        with _patch_user(None):
            response = client.post("/verification/nodes/stmt-a/code", params={"path": "analysis.py"}, content=b"x")
        self.assertEqual(response.status_code, 401)

    def test_a_file_is_stored_and_the_gates_reported(self):
        self._seed()
        response = self._upload("analysis.py", CODE_FILES["analysis.py"])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["gates"]["ok"])
        self.assertIn("test_analysis.py", response.json()["gates"]["missing"])

    def test_a_complete_sidecar_passes_the_gates(self):
        self._seed()
        for name, data in CODE_FILES.items():
            response = self._upload(name, data)
        self.assertTrue(response.json()["gates"]["ok"])

    def test_an_empty_body_is_400(self):
        self._seed()
        self.assertEqual(self._upload("analysis.py", b"").status_code, 400)

    def test_an_unknown_node_is_404(self):
        self.assertEqual(self._upload("analysis.py", b"x", node_id="nope").status_code, 404)

    def test_a_traversing_path_is_400(self):
        self._seed()
        self.assertEqual(self._upload("../../etc/passwd", b"x").status_code, 400)

    def test_an_oversized_file_is_400(self):
        self._seed()
        big = b"x" * (handlers.MAX_CODE_UPLOAD_BYTES + 1)
        self.assertEqual(self._upload("analysis.py", big).status_code, 400)

    def test_changing_code_after_a_run_marks_the_node_stale(self):
        self._seed()
        doc = store.get_node("stmt-a")
        doc["verification"]["reproducible"]["run"] = {"code_hash": "stale-hash"}
        store.put_node(doc)

        self._upload("analysis.py", CODE_FILES["analysis.py"])
        updated = store.get_node("stmt-a")
        self.assertEqual(updated["status"], "stale")
        self.assertEqual(updated["verification"]["reproducible"]["status"], "stale")

    def test_staleness_propagates_to_dependent_statements(self):
        self._seed()
        store.put_node({
            "id": "stmt-top", "kind": "statement", "subject": "ent-unit", "relation": "rel-r",
            "object": "ent-stim", "status": "verified", "depends_on": ["stmt-a"],
        })
        doc = store.get_node("stmt-a")
        doc["verification"]["reproducible"]["run"] = {"code_hash": "stale-hash"}
        store.put_node(doc)

        self._upload("analysis.py", CODE_FILES["analysis.py"])
        self.assertEqual(store.get_node("stmt-top")["status"], "stale")


class VerifyEndpointTestCase(ApiTestCase):
    def test_verifying_requires_a_login(self):
        self._seed()
        with _patch_user(None):
            response = client.post("/verification/nodes/stmt-a/verify", json={"axis": "reproducible"})
        self.assertEqual(response.status_code, 401)

    def test_an_unknown_node_is_404(self):
        with _patch_user(_ALICE):
            response = client.post("/verification/nodes/nope/verify", json={"axis": "reproducible"})
        self.assertEqual(response.status_code, 404)

    def test_a_node_without_code_cannot_be_run(self):
        self._seed()
        with _patch_user(_ALICE):
            response = client.post("/verification/nodes/ent-unit/verify", json={"axis": "reproducible"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("no code sidecar", response.json()["error"])

    def test_a_run_is_queued_and_pollable(self):
        self._seed()
        with _patch_user(_ALICE):
            response = client.post("/verification/nodes/stmt-a/verify", json={"axis": "reproducible"})
        body = response.json()
        self.assertEqual(body["kind"], "verify")
        self.assertEqual(body["node_id"], "stmt-a")
        self.assertEqual(client.get(f"/verification/jobs/{body['job_id']}").status_code, 200)

    def test_an_unknown_job_is_404(self):
        self.assertEqual(client.get("/verification/jobs/nope").status_code, 404)

    def test_a_run_records_its_outcome_on_the_node(self):
        self._seed()
        for name, data in CODE_FILES.items():
            store.put_code_file("stmt-a", name, data)
        record = {
            "axis": "reproducible", "passed": True, "note": "ok", "stage": "complete",
            "code_hash": "h", "env": "environment.lock", "result_hash": "r",
            "ran_at": "2026-08-26T00:00:00Z", "stamp": "2026-08-26T00-00-00", "log": "",
        }
        with patch.object(handlers.runner_mod, "verify_node", return_value=record):
            result = handlers._run_verification("stmt-a", "reproducible", _ALICE["orcid"])

        self.assertTrue(result["passed"])
        doc = store.get_node("stmt-a")
        self.assertEqual(doc["verification"]["reproducible"]["status"], "passed")
        self.assertEqual(store.list_runs("stmt-a")[0]["result_hash"], "r")

    def test_a_failed_run_propagates_staleness_to_dependents(self):
        self._seed()
        store.put_node({
            "id": "stmt-top", "kind": "statement", "subject": "ent-unit", "relation": "rel-r",
            "object": "ent-stim", "status": "verified", "depends_on": ["stmt-a"],
        })
        record = {
            "axis": "reproducible", "passed": False, "note": "changed", "stage": "analysis",
            "code_hash": "h", "env": "environment.lock", "ran_at": "t",
            "stamp": "2026-08-26T00-00-00", "log": "",
        }
        with patch.object(handlers.runner_mod, "verify_node", return_value=record):
            handlers._run_verification("stmt-a", "reproducible", _ALICE["orcid"])

        self.assertEqual(store.get_node("stmt-a")["status"], "failed")
        self.assertEqual(store.get_node("stmt-top")["status"], "stale")
        snapshot = client.get("/verification/graph").json()
        top = next(n for n in snapshot["nodes"] if n["id"] == "stmt-top")
        self.assertEqual(top["effective_status"], "failed")


class ApproveTestCase(ApiTestCase):
    def _approve(self, node_id="stmt-a", user=_ADMIN):
        with _patch_user(user):
            return client.post(f"/verification/nodes/{node_id}/approve")

    def test_approving_requires_an_admin(self):
        self._seed()
        self.assertEqual(self._approve(user=_ALICE).status_code, 403)

    def test_an_unknown_node_is_404(self):
        self.assertEqual(self._approve(node_id="nope").status_code, 404)

    def test_only_statements_carry_an_approvable_status(self):
        self._seed()
        self.assertEqual(self._approve(node_id="ent-unit").status_code, 400)

    def test_a_node_without_complete_code_cannot_be_promoted(self):
        self._seed()
        response = self._approve()
        self.assertEqual(response.status_code, 409)
        self.assertIn("code gates", response.json()["error"])

    def test_a_node_whose_reproducibility_has_not_passed_cannot_be_promoted(self):
        self._seed()
        for name, data in CODE_FILES.items():
            store.put_code_file("stmt-a", name, data)
        doc = store.get_node("stmt-a")
        doc["verification"]["reproducible"]["status"] = "not_attempted"
        doc["status"] = "proposed"
        store.put_node(doc)

        response = self._approve()
        self.assertEqual(response.status_code, 409)
        self.assertIn("reproducible axis", response.json()["error"])

    def test_a_node_with_green_gates_and_a_passing_run_is_promoted(self):
        self._seed()
        for name, data in CODE_FILES.items():
            store.put_code_file("stmt-a", name, data)
        doc = store.get_node("stmt-a")
        doc["status"] = "proposed"
        store.put_node(doc)

        response = self._approve()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "verified")
        self.assertEqual(response.json()["provenance"]["history"][-1]["action"], "approved")

    def test_a_node_missing_a_known_case_cannot_be_promoted(self):
        self._seed()
        files = dict(CODE_FILES, **{"known_cases.json": b"[]"})
        for name, data in files.items():
            store.put_code_file("stmt-a", name, data)
        self.assertEqual(self._approve().status_code, 409)


class AgentEndpointTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        handlers.agent_rate_limiter.reset()

    def test_an_agent_job_requires_a_login(self):
        with _patch_user(None):
            response = client.post("/verification/agent/jobs", json={"request": "x"})
        self.assertEqual(response.status_code, 401)

    def test_an_empty_request_is_400(self):
        with _patch_user(_ALICE):
            response = client.post("/verification/agent/jobs", json={"request": "   "})
        self.assertEqual(response.status_code, 400)

    def test_an_oversized_request_is_400(self):
        with _patch_user(_ALICE):
            response = client.post(
                "/verification/agent/jobs", json={"request": "x" * (handlers.agent_mod.MAX_REQUEST_BYTES + 1)}
            )
        self.assertEqual(response.status_code, 400)

    def test_a_job_is_queued_and_pollable(self):
        with _patch_user(_ALICE), patch.object(handlers, "_run_agent_job", return_value={}):
            response = client.post("/verification/agent/jobs", json={"request": "Verify CA3 units"})
        body = response.json()
        self.assertEqual(body["kind"], "agent")
        self.assertEqual(client.get(f"/verification/agent/jobs/{body['job_id']}").status_code, 200)

    def test_a_second_job_in_the_same_minute_is_rate_limited(self):
        with _patch_user(_ALICE), patch.object(handlers, "_run_agent_job", return_value={}):
            client.post("/verification/agent/jobs", json={"request": "one"})
            response = client.post("/verification/agent/jobs", json={"request": "two"})
        self.assertEqual(response.status_code, 429)

    def test_an_unknown_agent_job_is_404(self):
        self.assertEqual(client.get("/verification/agent/jobs/nope").status_code, 404)

    def test_the_outbox_is_the_only_way_into_the_graph(self):
        self._seed()

        def fake_run(job_self):
            outbox = f"{job_self.dir}/outbox"
            with open(f"{outbox}/nodes/stmt-new.json", "w", encoding="utf-8") as handle:
                json.dump({
                    "id": "stmt-new", "kind": "statement", "subject": "ent-unit",
                    "relation": "rel-r", "object": "ent-stim", "depends_on": ["stmt-a"],
                    "status": "verified",
                }, handle)
            with open(f"{outbox}/nodes/stmt-bad.json", "w", encoding="utf-8") as handle:
                json.dump({
                    "id": "stmt-bad", "kind": "statement", "subject": "ent-unit",
                    "relation": "rel-r", "object": "ent-stim", "depends_on": ["gone"],
                }, handle)
            import os

            os.makedirs(f"{outbox}/code/stmt-new", exist_ok=True)
            with open(f"{outbox}/code/stmt-new/analysis.py", "wb") as handle:
                handle.write(CODE_FILES["analysis.py"])
            return {"returncode": 0, "timed_out": False}

        with patch.object(handlers.agent_mod.AgentJob, "run", fake_run):
            result = handlers._run_agent_job("Verify CA3 units", _ALICE["orcid"])

        self.assertEqual(result["accepted"], ["stmt-new"])
        self.assertEqual(len(result["rejected"]), 1)

        created = store.get_node("stmt-new")
        self.assertEqual(created["status"], "proposed")
        self.assertIn("via agent job", created["provenance"]["author"])
        self.assertEqual(store.get_code_file("stmt-new", "analysis.py"), CODE_FILES["analysis.py"])
        self.assertIsNone(store.get_node("stmt-bad"))

    def test_a_job_that_writes_nothing_leaves_the_graph_unchanged(self):
        self._seed()
        before = len(store.list_nodes())
        with patch.object(handlers.agent_mod.AgentJob, "run",
                          lambda self: {"returncode": 1, "timed_out": True}):
            result = handlers._run_agent_job("Verify CA3 units", _ALICE["orcid"])
        self.assertEqual(result["accepted"], [])
        self.assertEqual(len(store.list_nodes()), before)


class IdGenerationTestCase(unittest.TestCase):
    def test_a_label_becomes_a_safe_slug(self):
        self.assertEqual(handlers._slug("Unit 123 (session A/B)"), "unit-123-session-a-b")

    def test_a_label_with_no_usable_characters_still_yields_an_id(self):
        self.assertTrue(handlers._slug("!!!"))

    def test_statement_ids_are_unique(self):
        first = handlers._generate_id({"kind": "statement"})
        self.assertNotEqual(first, handlers._generate_id({"kind": "statement"}))


class MissingNodeTestCase(ApiTestCase):
    def test_a_run_for_a_node_that_vanished_raises(self):
        with self.assertRaises(RuntimeError):
            handlers._run_verification("gone", "reproducible", _ALICE["orcid"])


if __name__ == "__main__":
    unittest.main()


class ErrorEnvelopeTestCase(ApiTestCase):
    """Every endpoint reports a store failure as a 500 with `{"error": ...}`."""

    def _boom(self, name):
        return patch.object(store, name, side_effect=RuntimeError("s3 down"))

    def test_the_manifest_reports_a_store_failure(self):
        with self._boom("get_manifest"):
            response = client.get("/verification/manifest")
        self.assertEqual((response.status_code, response.json()["error"]), (500, "s3 down"))

    def test_a_node_read_reports_a_store_failure(self):
        with self._boom("get_node"):
            response = client.get("/verification/nodes/stmt-a")
        self.assertEqual(response.status_code, 500)

    def test_a_code_listing_reports_a_store_failure(self):
        with self._boom("load_code_dir"):
            response = client.get("/verification/nodes/stmt-a/code")
        self.assertEqual(response.status_code, 500)

    def test_a_run_listing_reports_a_store_failure(self):
        with self._boom("list_runs"):
            response = client.get("/verification/nodes/stmt-a/runs")
        self.assertEqual(response.status_code, 500)

    def test_a_run_listing_rejects_an_unsafe_id(self):
        self.assertEqual(client.get("/verification/nodes/bad!id/runs").status_code, 400)

    def test_a_history_read_reports_a_store_failure(self):
        with self._boom("get_history"):
            response = client.get("/verification/nodes/stmt-a/history")
        self.assertEqual(response.status_code, 500)

    def test_a_history_read_rejects_an_unsafe_id(self):
        self.assertEqual(client.get("/verification/nodes/bad!id/history").status_code, 400)

    def test_creating_a_node_reports_a_read_failure(self):
        with _patch_user(_ALICE), self._boom("nodes_by_id"):
            response = client.post(
                "/verification/nodes", json={"kind": "entity", "entity_type": "unit", "label": "x"}
            )
        self.assertEqual(response.status_code, 500)

    def test_creating_a_node_reports_a_write_failure(self):
        with _patch_user(_ALICE), self._boom("put_node"):
            response = client.post(
                "/verification/nodes", json={"kind": "entity", "entity_type": "unit", "label": "x"}
            )
        self.assertEqual(response.status_code, 500)

    def test_a_code_upload_reports_a_store_failure(self):
        self._seed()
        with _patch_user(_ALICE), self._boom("put_code_file"):
            response = client.post(
                "/verification/nodes/stmt-a/code", params={"path": "analysis.py"}, content=b"x"
            )
        self.assertEqual(response.status_code, 500)

    def test_verifying_rejects_an_unsafe_id(self):
        with _patch_user(_ALICE):
            response = client.post("/verification/nodes/bad!id/verify", json={"axis": "reproducible"})
        self.assertEqual(response.status_code, 400)

    def test_approving_rejects_an_unsafe_id(self):
        with _patch_user(_ADMIN):
            self.assertEqual(client.post("/verification/nodes/bad!id/approve").status_code, 400)

    def test_approving_reports_a_write_failure(self):
        self._seed()
        for name, data in CODE_FILES.items():
            store.put_code_file("stmt-a", name, data)
        with _patch_user(_ADMIN), self._boom("put_node"):
            response = client.post("/verification/nodes/stmt-a/approve")
        self.assertEqual(response.status_code, 500)

    def test_a_file_the_store_refuses_is_400_not_500(self):
        # The store is the authority on the size limit; the handler's own
        # pre-check is a fast path, not the only guard.
        self._seed()
        with _patch_user(_ALICE), patch.object(store, "MAX_CODE_FILE_BYTES", 1):
            response = client.post(
                "/verification/nodes/stmt-a/code", params={"path": "analysis.py"}, content=b"too big"
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("limit is 1", response.json()["error"])
