"""Tests for the sandboxed Claude Agent SDK session's tool policy."""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from aind_metadata_viz.verification import agent_worker


def _hook(job_dir):
    """Build the write-confinement hook for *job_dir*."""
    return agent_worker.make_write_guard(job_dir)


def _call(guard, tool_name, tool_input):
    """Invoke the PreToolUse hook synchronously and return its decision."""
    return asyncio.run(guard({"tool_name": tool_name, "tool_input": tool_input}, None, None))


def _denied(decision):
    """True when a hook decision is a denial."""
    return decision.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


class ToolPolicyTestCase(unittest.TestCase):
    def test_no_network_reaching_tool_is_offered(self):
        for tool in ("WebFetch", "WebSearch"):
            self.assertNotIn(tool, agent_worker.AGENT_TOOLS)
            self.assertIn(tool, agent_worker.AGENT_DENIED_TOOLS)

    def test_the_session_can_author_and_test_code(self):
        for tool in ("Read", "Write", "Edit", "Bash"):
            self.assertIn(tool, agent_worker.AGENT_TOOLS)

    def test_unlisted_tools_are_denied_rather_than_prompted(self):
        # A headless session has nobody to prompt, so anything not pre-approved
        # has to be a hard deny.
        options = agent_worker.build_options("/tmp/job", "global.anthropic.claude-sonnet-5")
        self.assertEqual(options.permission_mode, "dontAsk")
        self.assertEqual(options.allowed_tools, agent_worker.AGENT_TOOLS)
        self.assertEqual(options.disallowed_tools, agent_worker.AGENT_DENIED_TOOLS)

    def test_only_the_jobs_own_settings_are_loaded(self):
        # Without the explicit list the SDK also reads the host's user and
        # local settings, which is host config leaking into a tenant job.
        options = agent_worker.build_options("/tmp/job", "m")
        self.assertEqual(options.setting_sources, ["project"])
        self.assertEqual(options.env.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY"), "1")

    def test_the_session_runs_in_the_job_directory(self):
        options = agent_worker.build_options("/tmp/job-42", "m")
        self.assertEqual(options.cwd, "/tmp/job-42")

    def test_the_model_is_passed_through(self):
        self.assertEqual(agent_worker.build_options("/tmp/j", "global.anthropic.claude-sonnet-5").model,
                         "global.anthropic.claude-sonnet-5")

    def test_an_empty_model_falls_back_to_the_sdk_default(self):
        self.assertIsNone(agent_worker.build_options("/tmp/j", "").model)

    def test_a_turn_limit_is_set(self):
        self.assertGreater(agent_worker.build_options("/tmp/j", "m").max_turns, 0)

    def test_the_write_guard_is_registered_as_a_pretooluse_hook(self):
        options = agent_worker.build_options("/tmp/j", "m")
        self.assertIn("PreToolUse", options.hooks)


class WriteConfinementTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = os.path.realpath(self.tmp.name)
        self.guard = _hook(self.job)
        os.makedirs(os.path.join(self.job, "outbox", "nodes"), exist_ok=True)

    def test_a_write_inside_the_outbox_is_allowed(self):
        decision = _call(self.guard, "Write", {"file_path": "outbox/nodes/stmt-a.json"})
        self.assertFalse(_denied(decision))

    def test_a_scratch_write_inside_the_job_directory_is_allowed(self):
        # The agent needs somewhere to draft and test code before promoting it.
        self.assertFalse(_denied(_call(self.guard, "Write", {"file_path": "scratch/analysis.py"})))

    def test_a_relative_escape_is_denied(self):
        self.assertTrue(_denied(_call(self.guard, "Write", {"file_path": "../../etc/passwd"})))

    def test_an_absolute_path_outside_the_job_is_denied(self):
        self.assertTrue(_denied(_call(self.guard, "Edit", {"file_path": "/etc/passwd"})))

    def test_writing_through_a_symlink_is_denied(self):
        # A symlink planted inside the job directory must not become a way to
        # write outside it.
        link = os.path.join(self.job, "escape")
        os.symlink("/etc", link)
        self.assertTrue(_denied(_call(self.guard, "Write", {"file_path": "escape/passwd"})))

    def test_the_job_directory_itself_is_allowed(self):
        self.assertFalse(_denied(_call(self.guard, "Write", {"file_path": "."})))

    def test_a_non_write_tool_is_not_path_checked(self):
        self.assertFalse(_denied(_call(self.guard, "Bash", {"command": "ls /etc"})))

    def test_a_write_with_no_path_is_left_alone(self):
        self.assertFalse(_denied(_call(self.guard, "Write", {})))

    def test_the_denial_tells_the_agent_where_output_belongs(self):
        decision = _call(self.guard, "Write", {"file_path": "/tmp/elsewhere"})
        reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("outbox/", reason)

    def test_every_write_tool_variant_is_covered(self):
        for tool in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
            self.assertTrue(_denied(_call(self.guard, tool, {"file_path": "/etc/shadow"})), tool)


class RenderTestCase(unittest.TestCase):
    class _Block:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _Message:
        def __init__(self, content=None, result=None):
            self.content = content or []
            if result is not None:
                self.result = result

    def test_text_blocks_are_rendered(self):
        message = self._Message(content=[self._Block(text="hello")])
        self.assertEqual(agent_worker.render(message), "hello")

    def test_tool_calls_are_summarized(self):
        message = self._Message(content=[self._Block(name="Write")])
        self.assertIn("[tool: Write]", agent_worker.render(message))

    def test_a_result_message_is_rendered(self):
        self.assertIn("done", agent_worker.render(self._Message(result="done")))

    def test_an_empty_message_renders_empty(self):
        self.assertEqual(agent_worker.render(self._Message()), "")


class MainTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(os.path.join(self.tmp.name, "prompt.txt"), "w", encoding="utf-8") as handle:
            handle.write("author a claim")

    def test_a_missing_job_directory_argument_is_a_usage_error(self):
        self.assertEqual(agent_worker.main(["agent_worker"]), 2)

    def test_a_successful_session_reports_its_outcome(self):
        async def fake(job_dir, prompt, model):
            return {"turns": 3, "summary": "ok"}

        with patch.object(agent_worker, "run_session", fake):
            self.assertEqual(agent_worker.main(["agent_worker", self.tmp.name]), 0)

    def test_a_failed_session_exits_nonzero_without_raising(self):
        async def boom(job_dir, prompt, model):
            raise RuntimeError("model unreachable")

        with patch.object(agent_worker, "run_session", boom):
            self.assertEqual(agent_worker.main(["agent_worker", self.tmp.name]), 1)

    def test_the_prompt_is_read_from_the_job_directory(self):
        seen = {}

        async def capture(job_dir, prompt, model):
            seen["prompt"] = prompt
            return {}

        with patch.object(agent_worker, "run_session", capture):
            agent_worker.main(["agent_worker", self.tmp.name])
        self.assertEqual(seen["prompt"], "author a claim")


class SessionTestCase(unittest.TestCase):
    def test_the_transcript_is_streamed_to_disk(self):
        class _Msg:
            def __init__(self, text):
                self.content = [RenderTestCase._Block(text=text)]

        async def fake_query(prompt, options):
            for text in ("first", "second"):
                yield _Msg(text)

        with tempfile.TemporaryDirectory() as job:
            with patch.object(agent_worker, "query", fake_query):
                outcome = asyncio.run(agent_worker.run_session(job, "go", "m"))
            with open(os.path.join(job, agent_worker.TRANSCRIPT_NAME), encoding="utf-8") as handle:
                body = handle.read()
        self.assertEqual(outcome["turns"], 2)
        self.assertIn("first", body)
        self.assertIn("second", body)

    def test_the_final_result_is_captured_as_the_summary(self):
        class _Result:
            content = []
            result = "authored 3 nodes"

        async def fake_query(prompt, options):
            yield _Result()

        with tempfile.TemporaryDirectory() as job:
            with patch.object(agent_worker, "query", fake_query):
                outcome = asyncio.run(agent_worker.run_session(job, "go", "m"))
        self.assertEqual(outcome["summary"], "authored 3 nodes")


if __name__ == "__main__":
    unittest.main()
