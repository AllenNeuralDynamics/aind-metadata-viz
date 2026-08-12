"""Tests for the pinpoint per-ORCID encrypted JSON blob endpoints."""

import json
import unittest
from io import BytesIO
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aind_metadata_viz.pinpoint.handlers import pinpoint_router
from aind_metadata_viz.pinpoint.store import (
    DecryptionError,
    JSON_CONTENT_TYPE,
    MAX_BLOB_BYTES,
    get_blob,
    get_file,
    list_blobs,
    store_blob,
    store_file,
)

_ZIP_CONTENT_TYPE = "application/zip"
_ZIP_BYTES = b"PK\x03\x04\x00\x00binary\x00\xff\xfe payload"

_app = FastAPI()
_app.include_router(pinpoint_router)
client = TestClient(_app)

_ALICE = {"orcid": "0000-0001-2345-6789", "name": "Alice", "is_admin": False}
_BOB = {"orcid": "0000-0002-9999-0000", "name": "Bob", "is_admin": False}


class _FakePaginator:
    def __init__(self, store):
        self._store = store

    def paginate(self, Bucket, Prefix="", Delimiter=None):
        keys = sorted(k for k in self._store if k.startswith(Prefix))
        yield {"Contents": [{"Key": k} for k in keys]}


class _FakeS3:
    def __init__(self):
        self._store = {}
        self._metadata = {}

    def put_object(self, Bucket, Key, Body, ContentType=None, Metadata=None):
        self._store[Key] = Body if isinstance(Body, bytes) else Body.encode()
        self._metadata[Key] = dict(Metadata or {})

    def get_object(self, Bucket, Key):
        if Key not in self._store:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject"
            )
        return {"Body": BytesIO(self._store[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self._store:
            raise ClientError(
                {"Error": {"Code": "NotFound", "Message": "Not Found"}}, "HeadObject"
            )
        return {"Metadata": self._metadata[Key]}

    def get_paginator(self, operation_name):
        return _FakePaginator(self._store)


def _patch_user(user):
    return patch(
        "aind_metadata_viz.auth.session.get_current_user", return_value=user
    )


class PinpointTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeS3()
        self._p = patch(
            "aind_metadata_viz.pinpoint.store._s3", return_value=self.fake
        )
        self._p.start()
        self.addCleanup(self._p.stop)


class TestStore(PinpointTestCase):
    def test_roundtrip_without_password(self):
        store_blob(_ALICE["orcid"], "probes", {"a": [1, 2, 3]})
        self.assertEqual(
            get_blob(_ALICE["orcid"], "probes"), {"a": [1, 2, 3]}
        )

    def test_stored_object_is_encrypted(self):
        store_blob(_ALICE["orcid"], "probes", {"secret": "trajectory-42"})
        raw = b"".join(self.fake._store.values())
        self.assertNotIn(b"trajectory-42", raw)
        envelope = json.loads(raw.decode())
        self.assertEqual(envelope["cipher"], "aes-256-gcm")
        self.assertEqual(envelope["key_source"], "server")

    def test_key_is_under_account_prefix(self):
        store_blob(_ALICE["orcid"], "probes", {})
        key = next(iter(self.fake._store))
        self.assertEqual(
            key, f"pinpoint/accounts/{_ALICE['orcid']}/probes.json"
        )

    def test_overwrite_replaces_previous_blob(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1})
        store_blob(_ALICE["orcid"], "probes", {"v": 2})
        self.assertEqual(len(self.fake._store), 1)
        self.assertEqual(get_blob(_ALICE["orcid"], "probes"), {"v": 2})

    def test_password_roundtrip(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1}, password="hunter2")
        self.assertEqual(
            get_blob(_ALICE["orcid"], "probes", password="hunter2"), {"v": 1}
        )

    def test_wrong_password_rejected(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1}, password="hunter2")
        with self.assertRaises(DecryptionError):
            get_blob(_ALICE["orcid"], "probes", password="nope")

    def test_missing_password_rejected(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1}, password="hunter2")
        with self.assertRaises(DecryptionError):
            get_blob(_ALICE["orcid"], "probes")

    def test_password_not_accepted_for_server_encrypted_blob(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1})
        with self.assertRaises(DecryptionError):
            get_blob(_ALICE["orcid"], "probes", password="hunter2")

    def test_other_account_cannot_read(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1})
        with self.assertRaises(FileNotFoundError):
            get_blob(_BOB["orcid"], "probes")

    def test_blob_cannot_be_replayed_under_another_account(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1})
        envelope = next(iter(self.fake._store.values()))
        self.fake._store[
            f"pinpoint/accounts/{_BOB['orcid']}/probes.json"
        ] = envelope
        with self.assertRaises(DecryptionError):
            get_blob(_BOB["orcid"], "probes")

    def test_blob_cannot_be_replayed_under_another_name(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1})
        envelope = next(iter(self.fake._store.values()))
        self.fake._store[
            f"pinpoint/accounts/{_ALICE['orcid']}/other.json"
        ] = envelope
        with self.assertRaises(DecryptionError):
            get_blob(_ALICE["orcid"], "other")

    def test_missing_blob_raises(self):
        with self.assertRaises(FileNotFoundError):
            get_blob(_ALICE["orcid"], "nothing")

    def test_list_blobs_only_returns_own(self):
        store_blob(_ALICE["orcid"], "b", {})
        store_blob(_ALICE["orcid"], "a", {})
        store_blob(_BOB["orcid"], "c", {})
        entries = list_blobs(_ALICE["orcid"])
        self.assertEqual([e["name"] for e in entries], ["a", "b"])

    def test_list_blobs_empty_account(self):
        self.assertEqual(list_blobs(_ALICE["orcid"]), [])

    def test_name_is_sanitised(self):
        store_blob(_ALICE["orcid"], "../../escape", {"v": 1})
        key = next(iter(self.fake._store))
        self.assertTrue(key.startswith(f"pinpoint/accounts/{_ALICE['orcid']}/"))
        self.assertNotIn("..", key)

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            store_blob(_ALICE["orcid"], "///", {"v": 1})

    def test_oversized_blob_rejected(self):
        with self.assertRaises(ValueError):
            store_blob(_ALICE["orcid"], "big", {"x": "y" * (MAX_BLOB_BYTES + 1)})

    def test_json_blob_records_json_content_type(self):
        store_blob(_ALICE["orcid"], "probes", {"v": 1})
        self.assertEqual(
            get_file(_ALICE["orcid"], "probes")[1], JSON_CONTENT_TYPE
        )


class TestFileStore(PinpointTestCase):
    def test_binary_roundtrip_preserves_bytes_and_content_type(self):
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE)
        self.assertEqual(
            get_file(_ALICE["orcid"], "exp"), (_ZIP_BYTES, _ZIP_CONTENT_TYPE)
        )

    def test_binary_payload_is_encrypted_at_rest(self):
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE)
        raw = b"".join(self.fake._store.values())
        self.assertNotIn(b"binary", raw)

    def test_content_type_defaults_to_octet_stream(self):
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES)
        self.assertEqual(
            get_file(_ALICE["orcid"], "exp")[1], "application/octet-stream"
        )

    def test_get_blob_rejects_non_json_blob(self):
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE)
        with self.assertRaises(ValueError):
            get_blob(_ALICE["orcid"], "exp")

    def test_binary_password_roundtrip(self):
        store_file(
            _ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE, password="pw"
        )
        self.assertEqual(
            get_file(_ALICE["orcid"], "exp", password="pw")[0], _ZIP_BYTES
        )
        with self.assertRaises(DecryptionError):
            get_file(_ALICE["orcid"], "exp", password="bad")

    def test_binary_blob_cannot_be_replayed_under_another_account(self):
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE)
        envelope = next(iter(self.fake._store.values()))
        self.fake._store[f"pinpoint/accounts/{_BOB['orcid']}/exp.json"] = envelope
        with self.assertRaises(DecryptionError):
            get_file(_BOB["orcid"], "exp")

    def test_oversized_binary_rejected(self):
        with self.assertRaises(ValueError):
            store_file(_ALICE["orcid"], "big", b"x" * (MAX_BLOB_BYTES + 1))

    def test_binary_replaces_previous_json_blob_of_same_name(self):
        store_blob(_ALICE["orcid"], "exp", {"v": 1})
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE)
        self.assertEqual(len(self.fake._store), 1)
        self.assertEqual(
            get_file(_ALICE["orcid"], "exp"), (_ZIP_BYTES, _ZIP_CONTENT_TYPE)
        )

    def test_list_reports_content_type_without_downloading_payloads(self):
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE)
        store_blob(_ALICE["orcid"], "probes", {"v": 1})
        with patch.object(
            self.fake, "get_object", side_effect=AssertionError("payload downloaded")
        ):
            entries = list_blobs(_ALICE["orcid"])
        self.assertEqual(
            {e["name"]: e["content_type"] for e in entries},
            {"exp": _ZIP_CONTENT_TYPE, "probes": JSON_CONTENT_TYPE},
        )

    def test_list_skips_blob_deleted_between_listing_and_head(self):
        store_file(_ALICE["orcid"], "exp", _ZIP_BYTES, _ZIP_CONTENT_TYPE)
        key = next(iter(self.fake._store))
        del self.fake._store[key]
        self.assertEqual(list_blobs(_ALICE["orcid"]), [])


class TestHandlers(PinpointTestCase):
    def test_get_requires_login(self):
        with _patch_user(None):
            resp = client.get("/pinpoint-get?name=probes")
        self.assertEqual(resp.status_code, 401)

    def test_post_requires_login(self):
        with _patch_user(None):
            resp = client.post("/pinpoint-post?name=probes", json={"v": 1})
        self.assertEqual(resp.status_code, 401)

    def test_post_then_get_roundtrip(self):
        with _patch_user(_ALICE):
            resp = client.post("/pinpoint-post?name=probes", json={"v": [1, 2]})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["key_source"], "server")
            resp = client.get("/pinpoint-get?name=probes")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"v": [1, 2]})

    def test_post_accepts_arbitrary_json_array(self):
        with _patch_user(_ALICE):
            client.post("/pinpoint-post?name=probes", json=[1, {"a": None}])
            resp = client.get("/pinpoint-get?name=probes")
        self.assertEqual(resp.json(), [1, {"a": None}])

    def test_password_roundtrip_via_handlers(self):
        with _patch_user(_ALICE):
            client.post("/pinpoint-post?name=probes&password=pw", json={"v": 1})
            unauthorized = client.get("/pinpoint-get?name=probes")
            authorized = client.get("/pinpoint-get?name=probes&password=pw")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.json(), {"v": 1})

    def test_wrong_password_returns_401(self):
        with _patch_user(_ALICE):
            client.post("/pinpoint-post?name=probes&password=pw", json={"v": 1})
            resp = client.get("/pinpoint-get?name=probes&password=bad")
        self.assertEqual(resp.status_code, 401)

    def test_other_user_gets_404(self):
        with _patch_user(_ALICE):
            client.post("/pinpoint-post?name=probes", json={"v": 1})
        with _patch_user(_BOB):
            resp = client.get("/pinpoint-get?name=probes")
        self.assertEqual(resp.status_code, 404)

    def test_get_without_name_lists_blobs(self):
        with _patch_user(_ALICE):
            client.post("/pinpoint-post?name=probes", json={"v": 1})
            resp = client.get("/pinpoint-get")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([e["name"] for e in resp.json()], ["probes"])

    def test_post_without_name_returns_400(self):
        with _patch_user(_ALICE):
            resp = client.post("/pinpoint-post", json={"v": 1})
        self.assertEqual(resp.status_code, 400)

    def test_post_empty_body_returns_400(self):
        with _patch_user(_ALICE):
            resp = client.post("/pinpoint-post?name=probes")
        self.assertEqual(resp.status_code, 400)

    def test_post_invalid_json_returns_400(self):
        with _patch_user(_ALICE):
            resp = client.post(
                "/pinpoint-post?name=probes",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_get_missing_blob_returns_404(self):
        with _patch_user(_ALICE):
            resp = client.get("/pinpoint-get?name=nope")
        self.assertEqual(resp.status_code, 404)

    def test_binary_post_then_get_roundtrip(self):
        with _patch_user(_ALICE):
            posted = client.post(
                "/pinpoint-post?name=exp",
                content=_ZIP_BYTES,
                headers={"Content-Type": _ZIP_CONTENT_TYPE},
            )
            resp = client.get("/pinpoint-get?name=exp")
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["content_type"], _ZIP_CONTENT_TYPE)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, _ZIP_BYTES)
        self.assertEqual(resp.headers["content-type"], _ZIP_CONTENT_TYPE)

    def test_binary_post_ignores_content_type_parameters(self):
        with _patch_user(_ALICE):
            client.post(
                "/pinpoint-post?name=exp",
                content=_ZIP_BYTES,
                headers={"Content-Type": f"{_ZIP_CONTENT_TYPE}; boundary=xyz"},
            )
            resp = client.get("/pinpoint-get?name=exp")
        self.assertEqual(resp.headers["content-type"], _ZIP_CONTENT_TYPE)

    def test_binary_post_requires_login(self):
        with _patch_user(None):
            resp = client.post(
                "/pinpoint-post?name=exp",
                content=_ZIP_BYTES,
                headers={"Content-Type": _ZIP_CONTENT_TYPE},
            )
        self.assertEqual(resp.status_code, 401)

    def test_binary_blob_is_not_readable_by_another_user(self):
        with _patch_user(_ALICE):
            client.post(
                "/pinpoint-post?name=exp",
                content=_ZIP_BYTES,
                headers={"Content-Type": _ZIP_CONTENT_TYPE},
            )
        with _patch_user(_BOB):
            resp = client.get("/pinpoint-get?name=exp")
        self.assertEqual(resp.status_code, 404)

    def test_list_includes_content_type(self):
        with _patch_user(_ALICE):
            client.post(
                "/pinpoint-post?name=exp",
                content=_ZIP_BYTES,
                headers={"Content-Type": _ZIP_CONTENT_TYPE},
            )
            resp = client.get("/pinpoint-get")
        self.assertEqual(
            [(e["name"], e["content_type"]) for e in resp.json()],
            [("exp", _ZIP_CONTENT_TYPE)],
        )


if __name__ == "__main__":
    unittest.main()
