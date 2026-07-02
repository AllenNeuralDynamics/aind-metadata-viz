import unittest
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from aind_metadata_viz.acquisitions.handlers import acquisitions_router
from aind_metadata_viz.acquisitions.store import (
    add_acquisition_type,
    add_scheduled_acquisition,
    get_allowed_types,
    get_scheduled_acquisition,
    get_scheduled_acquisitions,
)

_app = FastAPI()
_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_app.include_router(acquisitions_router)
client = TestClient(_app)


class _FakeS3:
    def __init__(self):
        self._store = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self._store[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):
        if Key not in self._store:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject")
        return {"Body": BytesIO(self._store[Key])}


def _s3_patch(fake):
    return patch("aind_metadata_viz.acquisitions.store._s3", return_value=fake)


class TestAcquisitionTypeStore(unittest.TestCase):
    def test_add_and_get_allowed_types(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            add_acquisition_type("behavior", "training")
            entries = get_allowed_types()
        self.assertEqual(entries, [{"platform": "behavior", "acquisition_type": "training"}])

    def test_add_acquisition_type_dedupes(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            add_acquisition_type("behavior", "training")
            add_acquisition_type("behavior", "training")
            entries = get_allowed_types()
        self.assertEqual(len(entries), 1)

    def test_add_acquisition_type_allows_same_type_different_platform(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            add_acquisition_type("behavior", "training")
            add_acquisition_type("ophys", "training")
            entries = get_allowed_types()
        self.assertEqual(len(entries), 2)

    def test_get_allowed_types_empty_when_unset(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            entries = get_allowed_types()
        self.assertEqual(entries, [])


class TestScheduledAcquisitionStore(unittest.TestCase):
    def test_add_scheduled_acquisition_rejects_unknown_type(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            with self.assertRaises(ValueError):
                add_scheduled_acquisition("123456", date.today(), "unknown-type")

    def test_add_scheduled_acquisition_returns_uuid_and_resolves_platform(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            add_acquisition_type("behavior", "training")
            acquisition_uuid = add_scheduled_acquisition("123456", date.today(), "training")
            record = get_scheduled_acquisition(acquisition_uuid)
        self.assertIsInstance(acquisition_uuid, str)
        self.assertEqual(record["subject_id"], "123456")
        self.assertEqual(record["platform"], "behavior")
        self.assertEqual(record["acquisition_type"], "training")

    def test_get_scheduled_acquisition_missing_returns_none(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            record = get_scheduled_acquisition("does-not-exist")
        self.assertIsNone(record)

    def test_get_scheduled_acquisitions_future_excludes_past(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            add_acquisition_type("behavior", "training")
            add_scheduled_acquisition("past-subject", date.today() - timedelta(days=1), "training")
            add_scheduled_acquisition("future-subject", date.today() + timedelta(days=1), "training")
            future_only = get_scheduled_acquisitions(include_past=False)
            all_records = get_scheduled_acquisitions(include_past=True)
        self.assertEqual(len(future_only), 1)
        self.assertEqual(future_only[0]["subject_id"], "future-subject")
        self.assertEqual(len(all_records), 2)

    def test_get_scheduled_acquisitions_today_counts_as_future(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            add_acquisition_type("behavior", "training")
            add_scheduled_acquisition("today-subject", date.today(), "training")
            future_only = get_scheduled_acquisitions(include_past=False)
        self.assertEqual(len(future_only), 1)
        self.assertEqual(future_only[0]["subject_id"], "today-subject")


class TestAcquisitionTypeHandlers(unittest.TestCase):
    def test_post_acquisition_type(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            response = client.post("/acquisition-types", json={"platform": "behavior", "acquisition_type": "training"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"platform": "behavior", "acquisition_type": "training"})

    def test_post_acquisition_type_missing_field(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            response = client.post("/acquisition-types", json={"platform": "behavior"})
        self.assertEqual(response.status_code, 422)

    def test_get_acquisition_types(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            client.post("/acquisition-types", json={"platform": "behavior", "acquisition_type": "training"})
            response = client.get("/acquisition-types")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"platform": "behavior", "acquisition_type": "training"}])


class TestScheduledAcquisitionHandlers(unittest.TestCase):
    def test_post_scheduled_acquisition(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            client.post("/acquisition-types", json={"platform": "behavior", "acquisition_type": "training"})
            response = client.post(
                "/scheduled-acquisitions",
                json={"subject_id": "123456", "date": date.today().isoformat(), "acquisition_type": "training"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("uuid", response.json())

    def test_post_scheduled_acquisition_unknown_type(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            response = client.post(
                "/scheduled-acquisitions",
                json={"subject_id": "123456", "date": date.today().isoformat(), "acquisition_type": "unknown"},
            )
        self.assertEqual(response.status_code, 400)

    def test_get_scheduled_acquisitions(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            client.post("/acquisition-types", json={"platform": "behavior", "acquisition_type": "training"})
            client.post(
                "/scheduled-acquisitions",
                json={"subject_id": "123456", "date": date.today().isoformat(), "acquisition_type": "training"},
            )
            response = client.get("/scheduled-acquisitions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_get_scheduled_acquisition_by_uuid(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            client.post("/acquisition-types", json={"platform": "behavior", "acquisition_type": "training"})
            post_response = client.post(
                "/scheduled-acquisitions",
                json={"subject_id": "123456", "date": date.today().isoformat(), "acquisition_type": "training"},
            )
            acquisition_uuid = post_response.json()["uuid"]
            response = client.get(f"/scheduled-acquisitions/{acquisition_uuid}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["subject_id"], "123456")
        self.assertEqual(body["platform"], "behavior")
        self.assertEqual(body["acquisition_type"], "training")

    def test_get_scheduled_acquisition_by_uuid_not_found(self):
        fake = _FakeS3()
        with _s3_patch(fake):
            response = client.get("/scheduled-acquisitions/does-not-exist")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
