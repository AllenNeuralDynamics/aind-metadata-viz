"""Unit tests for the /chat endpoint and supporting modules.

Bedrock and tool execution are mocked so the tests run offline.
"""

from __future__ import annotations

import asyncio
import copy
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aind_metadata_viz.chat import agent as agent_mod
from aind_metadata_viz.chat import handlers as handlers_mod
from aind_metadata_viz.chat.agent import ChatResult, ToolCallRecord, run_agent
from aind_metadata_viz.chat.handlers import chat_router
from aind_metadata_viz.chat.ratelimit import RateLimiter
from aind_metadata_viz.chat.tools import (
    DISABLED_TOOLS,
    invoke_tool,
    list_allowed_tools,
    to_bedrock_tool_spec,
)


def _make_app():
    app = FastAPI()
    app.include_router(chat_router)
    return app


# --- Fake Bedrock client ---------------------------------------------------


class _FakeBedrock:
    """Returns scripted converse responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        # Deep-copy because the agent appends to messages after calling.
        snapshot = {
            k: copy.deepcopy(v) if k == "messages" else v
            for k, v in kwargs.items()
        }
        self.calls.append(snapshot)
        if not self._responses:
            raise AssertionError("FakeBedrock ran out of responses")
        return self._responses.pop(0)


def _text_response(text, stop="end_turn"):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            }
        },
        "stopReason": stop,
    }


def _tool_use_response(tool_use_id, name, args):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": name,
                            "input": args,
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
    }


# --- Tests -----------------------------------------------------------------


class ToolsTests(unittest.TestCase):
    def test_disabled_tools_filtered(self):
        tools = asyncio.run(list_allowed_tools())
        names = {t.name for t in tools}
        self.assertTrue(DISABLED_TOOLS.isdisjoint(names))
        # And the disabled list isn't empty (sanity).
        self.assertTrue(len(DISABLED_TOOLS) > 0)

    def test_bedrock_tool_spec_shape(self):
        tools = asyncio.run(list_allowed_tools())
        spec = to_bedrock_tool_spec(tools[0])
        self.assertIn("toolSpec", spec)
        self.assertIn("name", spec["toolSpec"])
        self.assertIn("inputSchema", spec["toolSpec"])
        self.assertIn("json", spec["toolSpec"]["inputSchema"])
        # Description capped to 1024.
        self.assertLessEqual(len(spec["toolSpec"]["description"]), 1024)

    def test_invoke_disabled_tool_raises(self):
        with self.assertRaises(KeyError):
            asyncio.run(
                invoke_tool(
                    "identify_nwb_contents_with_s3_link",
                    {"s3_link": "s3://x"},
                    max_bytes=1000,
                )
            )

    def test_invoke_unknown_tool_raises(self):
        with self.assertRaises(KeyError):
            asyncio.run(
                invoke_tool("does_not_exist", {}, max_bytes=1000)
            )

    def test_invoke_tool_returns_text(self):
        # get_top_level_nodes is a pure-Python schema tool with no IO.
        text, is_error = asyncio.run(
            invoke_tool("get_top_level_nodes", {}, max_bytes=10000)
        )
        self.assertFalse(is_error)
        self.assertIn("subject", text)


class AgentTests(unittest.TestCase):
    def test_text_only_response(self):
        fake = _FakeBedrock([_text_response("Hello, world.")])
        result = asyncio.run(
            run_agent("hi", bedrock_client_factory=lambda: fake)
        )
        self.assertEqual(result.response, "Hello, world.")
        self.assertEqual(result.tool_calls, [])
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.iterations, 1)
        self.assertEqual(len(fake.calls), 1)

    def test_single_tool_call_then_answer(self):
        fake = _FakeBedrock(
            [
                _tool_use_response("tu1", "get_top_level_nodes", {}),
                _text_response("Top-level nodes listed."),
            ]
        )
        result = asyncio.run(
            run_agent(
                "what are the top level nodes?",
                bedrock_client_factory=lambda: fake,
            )
        )
        self.assertEqual(result.response, "Top-level nodes listed.")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].name, "get_top_level_nodes")
        self.assertFalse(result.tool_calls[0].is_error)
        self.assertEqual(result.iterations, 2)

    def test_multi_iteration_tool_chain(self):
        fake = _FakeBedrock(
            [
                _tool_use_response("a", "get_top_level_nodes", {}),
                _tool_use_response("b", "get_modality_types", {}),
                _text_response("All done."),
            ]
        )
        result = asyncio.run(
            run_agent(
                "tell me about modalities",
                bedrock_client_factory=lambda: fake,
            )
        )
        self.assertEqual(result.response, "All done.")
        self.assertEqual(len(result.tool_calls), 2)
        self.assertEqual(result.iterations, 3)

    def test_unknown_tool_call_handled(self):
        fake = _FakeBedrock(
            [
                _tool_use_response("x", "totally_made_up_tool", {}),
                _text_response("Sorry, I don't have that tool."),
            ]
        )
        result = asyncio.run(
            run_agent("do a thing", bedrock_client_factory=lambda: fake)
        )
        self.assertEqual(len(result.tool_calls), 1)
        self.assertTrue(result.tool_calls[0].is_error)
        self.assertEqual(result.response, "Sorry, I don't have that tool.")

    def test_tool_exception_recorded_not_raised(self):
        # Force invoke_tool to raise so we can verify the agent records it.
        fake = _FakeBedrock(
            [
                _tool_use_response("err", "get_top_level_nodes", {}),
                _text_response("Recovered."),
            ]
        )

        async def _boom(name, args, *, max_bytes):
            raise RuntimeError("boom")

        with patch.object(agent_mod, "invoke_tool", _boom):
            result = asyncio.run(
                run_agent("x", bedrock_client_factory=lambda: fake)
            )
        self.assertEqual(result.response, "Recovered.")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertTrue(result.tool_calls[0].is_error)
        self.assertIn("boom", result.tool_calls[0].output)

    def test_iteration_cap(self):
        # Always emit tool_use; agent should bail at MAX_ITERATIONS and
        # then make one final non-tool call.
        scripted = [
            _tool_use_response(f"id{i}", "get_top_level_nodes", {})
            for i in range(agent_mod.MAX_ITERATIONS)
        ] + [_text_response("Final answer.")]
        fake = _FakeBedrock(scripted)
        result = asyncio.run(
            run_agent("loop", bedrock_client_factory=lambda: fake)
        )
        self.assertEqual(result.stop_reason, "max_iterations")
        self.assertEqual(result.iterations, agent_mod.MAX_ITERATIONS)
        self.assertEqual(result.response, "Final answer.")

    def test_history_is_included(self):
        fake = _FakeBedrock([_text_response("ack")])
        asyncio.run(
            run_agent(
                "new message",
                history=[
                    {"role": "user", "content": "previous q"},
                    {"role": "assistant", "content": "previous a"},
                    {"role": "bogus", "content": "skip me"},
                    {"role": "user", "content": 123},  # type: ignore[dict-item]
                ],
                bedrock_client_factory=lambda: fake,
            )
        )
        sent_messages = fake.calls[0]["messages"]
        # 2 valid history turns + 1 new user message = 3.
        self.assertEqual(len(sent_messages), 3)
        self.assertEqual(sent_messages[0]["content"][0]["text"], "previous q")
        self.assertEqual(sent_messages[2]["content"][0]["text"], "new message")


class HandlerTests(unittest.TestCase):
    def setUp(self):
        handlers_mod.chat_rate_limiter.reset()
        self.app = _make_app()
        self.client = TestClient(self.app)

    def _patch_agent(self, result: ChatResult):
        async def _fake_run_agent(message, history=None, **kwargs):
            return result

        return patch.object(handlers_mod, "run_agent", _fake_run_agent)

    def test_happy_path(self):
        result = ChatResult(
            response="hi back",
            tool_calls=[
                ToolCallRecord(
                    name="get_top_level_nodes",
                    input={},
                    output="...",
                    is_error=False,
                )
            ],
            stop_reason="end_turn",
            iterations=2,
        )
        with self._patch_agent(result):
            r = self.client.post("/chat", json={"message": "hello"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["response"], "hi back")
        self.assertEqual(body["stop_reason"], "end_turn")
        self.assertEqual(body["iterations"], 2)
        self.assertEqual(len(body["tool_calls"]), 1)
        self.assertEqual(body["tool_calls"][0]["name"], "get_top_level_nodes")

    def test_missing_message_400(self):
        r = self.client.post("/chat", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("message", r.json()["error"])

    def test_empty_message_400(self):
        r = self.client.post("/chat", json={"message": "   "})
        self.assertEqual(r.status_code, 400)

    def test_non_string_message_400(self):
        r = self.client.post("/chat", json={"message": 42})
        self.assertEqual(r.status_code, 400)

    def test_oversize_message_400(self):
        big = "x" * (handlers_mod.MAX_MESSAGE_BYTES + 1)
        r = self.client.post("/chat", json={"message": big})
        self.assertEqual(r.status_code, 400)
        self.assertIn("exceeds", r.json()["error"])

    def test_invalid_history_shape_400(self):
        r = self.client.post(
            "/chat",
            json={"message": "hi", "history": "not a list"},
        )
        self.assertEqual(r.status_code, 400)

    def test_invalid_history_turn_400(self):
        r = self.client.post(
            "/chat",
            json={
                "message": "hi",
                "history": [{"role": "user", "content": 1}],
            },
        )
        self.assertEqual(r.status_code, 400)

    def test_invalid_role_400(self):
        r = self.client.post(
            "/chat",
            json={
                "message": "hi",
                "history": [{"role": "system", "content": "x"}],
            },
        )
        self.assertEqual(r.status_code, 400)

    def test_history_too_long_400(self):
        r = self.client.post(
            "/chat",
            json={
                "message": "hi",
                "history": [
                    {"role": "user", "content": "x"}
                    for _ in range(handlers_mod.MAX_HISTORY_TURNS + 1)
                ],
            },
        )
        self.assertEqual(r.status_code, 400)

    def test_invalid_json_body_400(self):
        r = self.client.post(
            "/chat",
            content="{not json",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(r.status_code, 400)

    def test_agent_failure_500(self):
        async def _boom(message, history=None, **kwargs):
            raise RuntimeError("kaboom")

        with patch.object(handlers_mod, "run_agent", _boom):
            r = self.client.post("/chat", json={"message": "hello"})
        self.assertEqual(r.status_code, 500)
        self.assertIn("Agent run failed", r.json()["error"])

    def test_rate_limit_per_minute(self):
        # Force a tight bucket so this finishes fast.
        tight = RateLimiter(per_minute=2, per_day=1000)
        with patch.object(handlers_mod, "chat_rate_limiter", tight):
            ok = ChatResult(response="ok", iterations=1)
            with self._patch_agent(ok):
                r1 = self.client.post("/chat", json={"message": "1"})
                r2 = self.client.post("/chat", json={"message": "2"})
                r3 = self.client.post("/chat", json={"message": "3"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)

    def test_rate_limit_per_day(self):
        tight = RateLimiter(per_minute=1000, per_day=1)
        with patch.object(handlers_mod, "chat_rate_limiter", tight):
            ok = ChatResult(response="ok", iterations=1)
            with self._patch_agent(ok):
                r1 = self.client.post("/chat", json={"message": "1"})
                r2 = self.client.post("/chat", json={"message": "2"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 429)


class RateLimiterTests(unittest.TestCase):
    def test_allows_burst_up_to_capacity(self):
        rl = RateLimiter(per_minute=3, per_day=100)
        for _ in range(3):
            ok, _ = rl.check("b", "ip")
            self.assertTrue(ok)
        ok, msg = rl.check("b", "ip")
        self.assertFalse(ok)
        self.assertIn("Rate limit", msg)

    def test_refill_over_time(self):
        rl = RateLimiter(per_minute=60, per_day=10000)  # 1/sec
        # Consume all 60 tokens.
        for _ in range(60):
            rl.check("b", "ip")
        ok, _ = rl.check("b", "ip")
        self.assertFalse(ok)
        # Simulate 1.5s passing.
        with rl._lock:
            rl._buckets[("b", "ip")].last_refill = time.time() - 1.5
        ok, _ = rl.check("b", "ip")
        self.assertTrue(ok)

    def test_daily_cap(self):
        rl = RateLimiter(per_minute=1000, per_day=2)
        self.assertTrue(rl.check("b", "ip")[0])
        self.assertTrue(rl.check("b", "ip")[0])
        ok, msg = rl.check("b", "ip")
        self.assertFalse(ok)
        self.assertIn("Daily limit", msg)

    def test_independent_buckets_and_clients(self):
        rl = RateLimiter(per_minute=1, per_day=100)
        self.assertTrue(rl.check("chat", "a")[0])
        self.assertFalse(rl.check("chat", "a")[0])
        self.assertTrue(rl.check("chat", "b")[0])
        self.assertTrue(rl.check("mcp", "a")[0])

    def test_invalid_limits(self):
        with self.assertRaises(ValueError):
            RateLimiter(per_minute=0, per_day=10)
        with self.assertRaises(ValueError):
            RateLimiter(per_minute=10, per_day=0)


if __name__ == "__main__":
    unittest.main()
