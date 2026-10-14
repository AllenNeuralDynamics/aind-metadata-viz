"""Temporary QC previews never overwrite real or temporary assets."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aind_metadata_viz import temporary_metadata as api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "STORE_PATH", str(tmp_path / "records.sqlite3"))
    monkeypatch.setattr(api, "asset_basics", Mock(return_value=pd.DataFrame(columns=["name"])))
    monkeypatch.setattr(api, "retrieve_records", Mock(return_value=Mock(records=[])))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_bare_qc_gets_generated_name_and_placeholders(client):
    qc = {"metrics": [{"name": "invalid metric for preview", "value": {"unknown": True}}]}
    response = client.post("/temporary-metadata", json=qc)
    assert response.status_code == 201
    result = response.json()
    assert result["name"].startswith("qc-test-")
    assert result["quality_control_url"].endswith(result["name"])
    fetched = client.get("/temporary-metadata", params={"name": result["name"]})
    assert fetched.headers["cache-control"] == "no-store"
    envelope = fetched.json()
    assert envelope["temporary"] is True
    assert envelope["expires_at"] == result["expires_at"]
    assert envelope["metadata"]["quality_control"] == qc
    assert envelope["metadata"]["location"] == ""
    assert envelope["metadata"]["data_description"]["subject_id"] == "temporary"


def test_full_metadata_is_preserved_and_duplicate_rejected(client):
    record = {"name": "preview", "quality_control": {"metrics": []}, "location": "s3://bucket/prefix",
              "data_description": {"project_name": "example"}, "custom": {"keep": True}}
    assert client.post("/temporary-metadata", json=record).status_code == 201
    assert client.get("/temporary-metadata?name=preview").json()["metadata"] == record
    assert client.post("/temporary-metadata", json=record).status_code == 409
    assert client.get("/temporary-metadata?name=preview").json()["metadata"] == record


def test_expiry_is_exactly_thirty_days_and_allows_name_reuse(client, monkeypatch):
    now = api._now()
    monkeypatch.setattr(api, "_now", lambda: now)
    created = client.post("/temporary-metadata?name=preview", json={"metrics": []}).json()
    assert created["expires_at"] == (now + timedelta(days=30)).isoformat()
    monkeypatch.setattr(api, "_now", lambda: now + timedelta(days=30))
    assert client.get("/temporary-metadata?name=preview").status_code == 404
    assert client.post("/temporary-metadata?name=preview", json={"metrics": []}).status_code == 201


@pytest.mark.parametrize("source", ["cache", "docdb"])
def test_real_name_collision(client, source):
    if source == "cache":
        api.asset_basics.return_value = pd.DataFrame({"name": ["real"]})
    else:
        api.retrieve_records.return_value = Mock(records=[{"name": "real"}])
    assert client.post("/temporary-metadata?name=real", json={"metrics": []}).status_code == 409
    api.asset_basics.assert_called_once_with()
    assert client.get("/temporary-metadata?name=real").status_code == 404


@pytest.mark.parametrize("source", ["asset_basics", "retrieve_records"])
def test_uniqueness_outage_rejects_upload(client, source):
    getattr(api, source).side_effect = RuntimeError("unavailable")
    assert client.post("/temporary-metadata?name=test", json={"metrics": []}).status_code == 503
    assert client.get("/temporary-metadata?name=test").status_code == 404


@pytest.mark.parametrize("payload", [[], {}, {"quality_control": []}, {"name": "", "quality_control": {}},
                                     {"name": 1, "quality_control": {}}])
def test_invalid_envelopes_rejected(client, payload):
    assert client.post("/temporary-metadata", json=payload).status_code == 422


def test_name_mismatch_bad_json_and_size_limit(client, monkeypatch):
    assert client.post("/temporary-metadata?name=other", json={"name": "one", "quality_control": {}}).status_code == 422
    assert client.post("/temporary-metadata", content="{broken").status_code == 422
    monkeypatch.setattr(api, "MAX_BYTES", 10)
    assert client.post("/temporary-metadata", json={"metrics": []}).status_code == 413


def test_concurrent_uploads_cannot_overwrite(client):
    def upload(_):
        return client.post("/temporary-metadata?name=shared", json={"metrics": []}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(upload, range(2))) == [201, 409]
