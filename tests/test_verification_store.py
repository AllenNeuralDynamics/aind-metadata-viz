"""Tests for the verification graph's S3 store, against a fake S3 double."""

import json
import unittest
from io import BytesIO
from unittest.mock import patch

from botocore.exceptions import ClientError

from aind_metadata_viz.verification import store


class _FakePaginator:
    """Stands in for boto3's list_objects_v2 paginator."""

    def __init__(self, objects):
        """Hold a reference to the fake bucket's contents."""
        self._objects = objects

    def paginate(self, Bucket, Prefix="", **kwargs):
        """Yield one page of every key under *Prefix*."""
        keys = sorted(k for k in self._objects if k.startswith(Prefix))
        yield {"Contents": [{"Key": k, "Size": len(self._objects[k])} for k in keys]}


class _FakeS3:
    """An in-memory stand-in for the handful of S3 calls the store makes."""

    def __init__(self):
        """Start with an empty bucket."""
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType=None, **kwargs):
        """Store an object's bytes."""
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):
        """Return an object, raising NoSuchKey when it is absent."""
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "nope"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def get_paginator(self, operation_name):
        """Return the listing paginator."""
        return _FakePaginator(self.objects)


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeS3()
        self._patch = patch.object(store, "_s3", return_value=self.fake)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _entity(self, node_id="ent-unit-1"):
        return {"id": node_id, "kind": "entity", "entity_type": "unit", "label": node_id}


class IdSafetyTestCase(StoreTestCase):
    def test_a_plain_id_is_accepted(self):
        self.assertEqual(store.safe_id("stmt-01J.abc_x-1"), "stmt-01J.abc_x-1")

    def test_path_traversal_is_refused(self):
        for bad in ("../secret", "a/b", "", "/abs", ".hidden", "x" * 200):
            with self.assertRaises(store.InvalidId):
                store.safe_id(bad)

    def test_a_nested_code_path_is_accepted(self):
        self.assertEqual(store.safe_code_path("tests/test_analysis.py"), "tests/test_analysis.py")

    def test_a_code_path_cannot_escape_its_directory(self):
        for bad in ("../analysis.py", "a/../../b", "/etc/passwd", ""):
            with self.assertRaises(store.InvalidId):
                store.safe_code_path(bad)


class NodeStorageTestCase(StoreTestCase):
    def test_a_node_round_trips(self):
        store.put_node(self._entity())
        self.assertEqual(store.get_node("ent-unit-1")["label"], "ent-unit-1")

    def test_an_unknown_node_is_none(self):
        self.assertIsNone(store.get_node("ent-nope"))

    def test_writing_stamps_created_and_updated(self):
        written = store.put_node(self._entity())
        self.assertIn("created", written["provenance"])
        self.assertIn("updated", written["provenance"])

    def test_an_overwrite_archives_the_previous_version(self):
        store.put_node(self._entity())
        updated = store.get_node("ent-unit-1")
        updated["label"] = "renamed"
        store.put_node(updated)

        history = store.get_history("ent-unit-1")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["label"], "ent-unit-1")
        self.assertEqual(store.get_node("ent-unit-1")["label"], "renamed")

    def test_archiving_can_be_skipped(self):
        store.put_node(self._entity())
        store.put_node(self._entity(), archive_previous=False)
        self.assertEqual(store.get_history("ent-unit-1"), [])

    def test_history_is_newest_first(self):
        store.put_node(self._entity())
        for label in ("second", "third"):
            doc = store.get_node("ent-unit-1")
            doc["label"] = label
            store.put_node(doc)
        history = store.get_history("ent-unit-1")
        self.assertEqual([h["label"] for h in history], ["second", "ent-unit-1"])

    def test_listing_returns_every_node(self):
        store.put_node(self._entity("ent-a"))
        store.put_node(self._entity("ent-b"))
        self.assertEqual({n["id"] for n in store.list_nodes()}, {"ent-a", "ent-b"})

    def test_listing_ignores_non_json_keys(self):
        store.put_node(self._entity("ent-a"))
        self.fake.objects[f"{store.NODES_PREFIX}/stray.txt"] = b"junk"
        self.assertEqual(len(store.list_nodes()), 1)

    def test_nodes_by_id_keys_on_the_document_id(self):
        store.put_node(self._entity("ent-a"))
        self.assertIn("ent-a", store.nodes_by_id())


class CodeStorageTestCase(StoreTestCase):
    def test_a_code_file_round_trips(self):
        store.put_code_file("stmt-a", "analysis.py", b"print(1)\n")
        self.assertEqual(store.get_code_file("stmt-a", "analysis.py"), b"print(1)\n")

    def test_an_absent_code_file_is_none(self):
        self.assertIsNone(store.get_code_file("stmt-a", "analysis.py"))

    def test_listing_reports_paths_and_sizes_sorted(self):
        store.put_code_file("stmt-a", "environment.lock", b"numpy==1.26.4\n")
        store.put_code_file("stmt-a", "analysis.py", b"x")
        listing = store.list_code_files("stmt-a")
        self.assertEqual([f["path"] for f in listing], ["analysis.py", "environment.lock"])
        self.assertEqual(listing[0]["size"], 1)

    def test_loading_a_directory_returns_every_file(self):
        store.put_code_file("stmt-a", "analysis.py", b"a")
        store.put_code_file("stmt-a", "tests/test_analysis.py", b"b")
        self.assertEqual(set(store.load_code_dir("stmt-a")), {"analysis.py", "tests/test_analysis.py"})

    def test_an_oversized_file_is_refused(self):
        with self.assertRaises(ValueError):
            store.put_code_file("stmt-a", "analysis.py", b"x" * (store.MAX_CODE_FILE_BYTES + 1))


class RunStorageTestCase(StoreTestCase):
    def test_a_run_records_its_result_and_log(self):
        prefix = store.put_run("stmt-a", "2026-08-26T00-00-00", {"axis": "reproducible", "ran_at": "t1"}, "log text")
        self.assertTrue(prefix.endswith("2026-08-26T00-00-00"))
        self.assertEqual(store.get_run_log("stmt-a", "2026-08-26T00-00-00"), "log text")

    def test_an_absent_run_log_is_none(self):
        self.assertIsNone(store.get_run_log("stmt-a", "2026-08-26T00-00-00"))

    def test_runs_are_listed_newest_first(self):
        store.put_run("stmt-a", "2026-08-26T00-00-00", {"ran_at": "2026-08-26T00:00:00"})
        store.put_run("stmt-a", "2026-08-27T00-00-00", {"ran_at": "2026-08-27T00:00:00"})
        runs = store.list_runs("stmt-a")
        self.assertEqual([r["ran_at"] for r in runs], ["2026-08-27T00:00:00", "2026-08-26T00:00:00"])

    def test_each_listed_run_omits_its_full_log_text(self):
        store.put_run(
            "stmt-a", "2026-08-26T00-00-00",
            {"ran_at": "t", "stamp": "2026-08-26T00-00-00", "log": "big"}, "big",
        )
        listed = store.list_runs("stmt-a")[0]
        self.assertNotIn("log", listed)
        self.assertEqual(listed["stamp"], "2026-08-26T00-00-00")
        self.assertEqual(store.get_run_log("stmt-a", listed["stamp"]), "big")


class DerivedDocumentTestCase(StoreTestCase):
    def _seed(self):
        store.put_node({"id": "ent-unit", "kind": "entity", "entity_type": "unit", "label": "Unit"})
        store.put_node({"id": "ent-stim", "kind": "entity", "entity_type": "stimulus", "label": "vis1"})
        store.put_node({
            "id": "rel-r", "kind": "relation", "label": "responds to",
            "signature": {"subject": ["unit"], "object": ["stimulus"]},
        })
        store.put_node({
            "id": "stmt-a", "kind": "statement", "subject": "ent-unit",
            "relation": "rel-r", "object": "ent-stim", "status": "verified", "depends_on": [],
        })

    def test_recompiling_writes_the_snapshot_and_the_manifest(self):
        self._seed()
        snapshot = store.recompile()
        self.assertEqual(len(snapshot["nodes"]), 4)
        self.assertIn(store.SNAPSHOT_KEY, self.fake.objects)
        self.assertIn(store.MANIFEST_KEY, self.fake.objects)

    def test_recompiling_accepts_documents_already_in_hand(self):
        snapshot = store.recompile([{"id": "x", "kind": "entity", "label": "X"}])
        self.assertEqual(len(snapshot["nodes"]), 1)

    def test_the_snapshot_is_built_on_demand_when_missing(self):
        self._seed()
        self.assertEqual(len(store.get_snapshot()["nodes"]), 4)

    def test_an_empty_graph_returns_an_empty_snapshot(self):
        snapshot = store.get_snapshot(rebuild_if_missing=False)
        self.assertEqual(snapshot["nodes"], [])

    def test_the_manifest_is_built_on_demand_when_missing(self):
        self._seed()
        self.assertEqual(len(store.get_manifest()), 4)

    def test_a_stored_snapshot_is_served_as_written(self):
        self.fake.objects[store.SNAPSHOT_KEY] = json.dumps({"generated": "t", "nodes": [], "edges": []}).encode()
        self.assertEqual(store.get_snapshot()["generated"], "t")


class S3ErrorTestCase(StoreTestCase):
    def test_a_non_missing_s3_error_propagates(self):
        def boom(Bucket, Key):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetObject")

        self.fake.get_object = boom
        with self.assertRaises(ClientError):
            store.get_node("ent-unit-1")


if __name__ == "__main__":
    unittest.main()


class ClientTestCase(unittest.TestCase):
    """The store's boto3 client factory, unpatched."""

    def test_the_client_is_built_for_s3(self):
        self.assertEqual(store._s3().meta.service_model.service_name, "s3")
