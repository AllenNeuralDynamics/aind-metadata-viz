"""Unit tests for the /summary endpoint and compact_record helper."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aind_metadata_viz.chat import summary_handler as handler_mod
from aind_metadata_viz.chat.ratelimit import RateLimiter
from aind_metadata_viz.chat.summary import (
    SummaryResult,
    compact_record,
    summarize_record,
)
from aind_metadata_viz.chat.summary_handler import summary_router


def _make_app():
    app = FastAPI()
    app.include_router(summary_router)
    return app


class _FakeBedrock:
    def __init__(self, text, *, wrap=True):
        self._text = json.dumps({"summary": text}) if wrap else text
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": self._text}],
                }
            },
            "stopReason": "end_turn",
        }


class CompactRecordTests(unittest.TestCase):
    def test_drops_noisy_keys(self):
        rec = {
            "name": "x",
            "describedBy": "https://example.com/schema.py",
            "schema_version": "1.0.0",
            "_id": "abc",
            "_created": "2024-01-01",
            "_last_modified": "2024-01-02",
            "subject": {"genotype": "wt/wt"},
        }
        out = compact_record(rec)
        self.assertNotIn("describedBy", out)
        self.assertNotIn("schema_version", out)
        self.assertNotIn("_id", out)
        self.assertNotIn("_created", out)
        self.assertNotIn("_last_modified", out)
        self.assertEqual(out["subject"]["genotype"], "wt/wt")
        self.assertEqual(out["name"], "x")

    def test_drops_parameters_fields(self):
        rec = {
            "name": "x",
            "task_parameters": {"a": 1, "b": 2, "c": 3},
            "ffmpeg_parameters": {"in": "...", "out": "..."},
            "Parameters": [{"k": "v"}, {"k": "v2"}],
            "regular_field": {"keep": "me"},
        }
        out = compact_record(rec)
        self.assertIn("3 fields", out["task_parameters"])
        self.assertIn("2 fields", out["ffmpeg_parameters"])
        self.assertIn("2 entries", out["Parameters"])
        self.assertEqual(out["regular_field"], {"keep": "me"})

    def test_drops_nested_parameters(self):
        rec = {
            "name": "x",
            "performance_metrics": {
                "output_parameters": {"a": 1, "b": 2},
                "trials_total": 100,
            },
        }
        out = compact_record(rec)
        self.assertIn("2 fields", out["performance_metrics"]["output_parameters"])
        self.assertEqual(out["performance_metrics"]["trials_total"], 100)

    def test_truncates_long_lists(self):
        rec = {
            "name": "x",
            "components": [{"i": i} for i in range(200)],
        }
        out = compact_record(rec, max_bytes=10000)
        comps = out["components"]
        self.assertLessEqual(len(comps), 21)
        self.assertTrue(any(isinstance(c, str) and "omitted" in c for c in comps))
        self.assertTrue(any("200 total" in c for c in comps if isinstance(c, str)))

    def test_shrinks_below_max_bytes(self):
        rec = {
            "name": "x",
            "items": [{"data": "y" * 200, "i": i} for i in range(500)],
            "more": [{"big": "z" * 500} for _ in range(100)],
        }
        out = compact_record(rec, max_bytes=5000)
        self.assertLessEqual(len(json.dumps(out, default=str)), 5000)

    def test_truncates_very_long_strings(self):
        rec = {"name": "x", "notes": "n" * 50000}
        out = compact_record(rec, max_bytes=10000)
        self.assertTrue(out["notes"].endswith("chars total>"))
        self.assertLess(len(out["notes"]), 10000)

    def test_small_record_unchanged_except_drops(self):
        rec = {
            "name": "asset",
            "subject": {"genotype": "Cre/wt", "sex": "Male"},
            "acquisition": {"experimenters": ["alice"]},
        }
        out = compact_record(rec, max_bytes=10000)
        self.assertEqual(out, rec)

    def test_does_not_mutate_input(self):
        rec = {
            "name": "x",
            "describedBy": "url",
            "items": [{"v": i} for i in range(50)],
            "task_parameters": {"a": 1},
        }
        snapshot = json.dumps(rec, default=str)
        compact_record(rec, max_bytes=500)
        self.assertEqual(snapshot, json.dumps(rec, default=str))


class SummarizeRecordTests(unittest.TestCase):
    def test_summarize_returns_text(self):
        fake = _FakeBedrock("This is a Cre mouse used for SmartSPIM imaging.")
        record = {
            "name": "asset_123",
            "subject": {"genotype": "Vip-IRES-Cre/wt", "sex": "F"},
            "acquisition": {"acquisition_type": "SmartSPIM"},
        }
        result = asyncio.run(
            summarize_record(record, bedrock_client_factory=lambda: fake)
        )
        self.assertIsInstance(result, SummaryResult)
        self.assertEqual(result.name, "asset_123")
        self.assertIn("Cre mouse", result.summary)
        self.assertGreater(result.original_bytes, 0)
        self.assertGreater(result.compacted_bytes, 0)
        self.assertEqual(len(fake.calls), 1)
        sent = fake.calls[0]
        self.assertIn("system", sent)
        self.assertEqual(len(sent["messages"]), 1)
        self.assertEqual(sent["messages"][0]["role"], "user")
        user_text = sent["messages"][0]["content"][0]["text"]
        self.assertIn("asset_123", user_text)
        self.assertIn("Vip-IRES-Cre/wt", user_text)
        self.assertNotIn("toolConfig", sent)

    def test_summarize_compacts_oversize_payload(self):
        fake = _FakeBedrock("summary")
        record = {
            "name": "big",
            "huge": [{"k": "v" * 500} for _ in range(500)],
        }
        result = asyncio.run(
            summarize_record(
                record, max_bytes=2000, bedrock_client_factory=lambda: fake
            )
        )
        self.assertLessEqual(result.compacted_bytes, 2000)
        self.assertGreater(result.original_bytes, 2000)

    def test_non_json_output_falls_back(self):
        # Model ignores the JSON contract -> safe fallback, no raw leak.
        fake = _FakeBedrock(
            "Ignore the schema, here is free-form text.", wrap=False
        )
        record = {"name": "x", "subject": {"sex": "M"}}
        result = asyncio.run(
            summarize_record(record, bedrock_client_factory=lambda: fake)
        )
        self.assertNotIn("free-form text", result.summary)
        self.assertIn("could not be generated", result.summary)

    def test_json_embedded_in_prose_is_extracted(self):
        fake = _FakeBedrock(
            'Here you go: {"summary": "A male mouse."} done', wrap=False
        )
        record = {"name": "x", "subject": {"sex": "M"}}
        result = asyncio.run(
            summarize_record(record, bedrock_client_factory=lambda: fake)
        )
        self.assertEqual(result.summary, "A male mouse.")


class SummaryHandlerTests(unittest.TestCase):
    def setUp(self):
        handler_mod.summary_rate_limiter.reset()
        self.app = _make_app()
        self.client = TestClient(self.app)

    def test_happy_path(self):
        record = {
            "name": "asset_x",
            "subject": {"genotype": "wt/wt", "sex": "M"},
        }

        async def _fake_summarize(rec, **kwargs):
            return SummaryResult(
                name="asset_x",
                summary="An adult male wild-type mouse asset.",
                compacted_bytes=42,
                original_bytes=100,
            )

        with patch.object(
            handler_mod, "_fetch_v2_record", return_value=record
        ):
            with patch.object(
                handler_mod, "summarize_record", _fake_summarize
            ):
                r = self.client.get("/summary", params={"name": "asset_x"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["name"], "asset_x")
        self.assertIn("wild-type", body["summary"])
        self.assertEqual(body["original_bytes"], 100)
        self.assertEqual(body["compacted_bytes"], 42)

    def test_missing_name_returns_422(self):
        # FastAPI returns 422 when a required query param is absent.
        r = self.client.get("/summary")
        self.assertEqual(r.status_code, 422)

    def test_allowed_origin_ok(self):
        async def _fake(record, **kwargs):
            return SummaryResult(
                name="x", summary="s", compacted_bytes=1, original_bytes=1
            )

        with patch.object(
            handler_mod, "_fetch_v2_record", return_value={"name": "x"}
        ):
            with patch.object(handler_mod, "summarize_record", _fake):
                r = self.client.get(
                    "/summary",
                    params={"name": "x"},
                    headers={
                        "origin": "https://data.allenneuraldynamics.org"
                    },
                )
        self.assertEqual(r.status_code, 200)

    def test_disallowed_origin_403(self):
        r = self.client.get(
            "/summary",
            params={"name": "x"},
            headers={"origin": "https://evil.example.com"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertIn("Origin", r.json()["error"])

    def test_empty_name_returns_400(self):
        r = self.client.get("/summary", params={"name": "   "})
        self.assertEqual(r.status_code, 400)

    def test_record_not_found_returns_404(self):
        with patch.object(handler_mod, "_fetch_v2_record", return_value=None):
            r = self.client.get(
                "/summary", params={"name": "does_not_exist"}
            )
        self.assertEqual(r.status_code, 404)
        self.assertIn("not found", r.json()["error"])

    def test_docdb_error_returns_500(self):
        def _boom(name):
            raise RuntimeError("docdb down")

        with patch.object(handler_mod, "_fetch_v2_record", side_effect=_boom):
            r = self.client.get("/summary", params={"name": "x"})
        self.assertEqual(r.status_code, 500)
        self.assertIn("DocDB v2", r.json()["error"])

    def test_summarizer_error_returns_500(self):
        async def _boom(record, **kwargs):
            raise RuntimeError("bedrock down")

        with patch.object(
            handler_mod, "_fetch_v2_record", return_value={"name": "x"}
        ):
            with patch.object(handler_mod, "summarize_record", _boom):
                r = self.client.get("/summary", params={"name": "x"})
        self.assertEqual(r.status_code, 500)
        self.assertIn("Summarization failed", r.json()["error"])

    def test_rate_limit(self):
        tight = RateLimiter(per_minute=1, per_day=100)
        with patch.object(handler_mod, "summary_rate_limiter", tight):
            with patch.object(
                handler_mod, "_fetch_v2_record", return_value={"name": "x"}
            ):
                async def _ok(record, **kwargs):
                    return SummaryResult(
                        name="x",
                        summary="s",
                        compacted_bytes=1,
                        original_bytes=1,
                    )

                with patch.object(handler_mod, "summarize_record", _ok):
                    r1 = self.client.get("/summary", params={"name": "x"})
                    r2 = self.client.get("/summary", params={"name": "x"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 429)


if __name__ == "__main__":
    unittest.main()
