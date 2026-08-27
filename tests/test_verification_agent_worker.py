"""Tests for the sandboxed Claude Agent SDK session's tool policy."""

import asyncio
import json
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


class ClipTestCase(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(agent_worker.clip("hello", 50), "hello")

    def test_newlines_are_collapsed_to_one_line(self):
        self.assertEqual(agent_worker.clip("a\n  b\n\tc", 50), "a b c")

    def test_long_text_is_truncated_and_says_how_much_was_dropped(self):
        clipped = agent_worker.clip("x" * 30, 10)
        self.assertTrue(clipped.startswith("x" * 10))
        self.assertIn("+20 more chars", clipped)


class ToolSummaryTestCase(unittest.TestCase):
    def test_a_bash_command_is_shown_in_full(self):
        summary = agent_worker.summarize_tool_input("Bash", {"command": "pytest -q", "description": "run tests"})
        self.assertEqual(summary, "pytest -q")

    def test_a_file_tool_shows_its_path(self):
        for tool in ("Read", "Edit", "MultiEdit"):
            self.assertEqual(
                agent_worker.summarize_tool_input(tool, {"file_path": "outbox/nodes/a.json"}),
                "outbox/nodes/a.json", tool)

    def test_a_write_says_how_much_it_is_writing(self):
        summary = agent_worker.summarize_tool_input("Write", {"file_path": "a.py", "content": "y" * 40})
        # clip() collapses runs of whitespace, so the separator is one space.
        self.assertEqual(summary, "a.py (40 chars)")

    def test_a_search_shows_pattern_and_path(self):
        summary = agent_worker.summarize_tool_input("Grep", {"pattern": "responds_to", "path": "outbox/"})
        self.assertEqual(summary, "responds_to outbox/")

    def test_an_unknown_tool_falls_back_to_its_whole_input(self):
        summary = agent_worker.summarize_tool_input("Mystery", {"b": 2, "a": 1})
        self.assertEqual(summary, '{"a": 1, "b": 2}')

    def test_a_known_tool_with_none_of_its_fields_falls_back(self):
        self.assertIn("other", agent_worker.summarize_tool_input("Bash", {"other": "x"}))

    def test_a_non_dict_input_is_stringified(self):
        self.assertEqual(agent_worker.summarize_tool_input("Bash", "raw"), "raw")

    def test_a_long_command_is_truncated(self):
        summary = agent_worker.summarize_tool_input("Bash", {"command": "x" * 900})
        self.assertLess(len(summary), 400)
        self.assertIn("more chars", summary)


class ToolResultSummaryTestCase(unittest.TestCase):
    def test_a_plain_string_result(self):
        self.assertEqual(agent_worker.summarize_tool_result("3 passed"), "3 passed")

    def test_a_block_list_result_is_flattened(self):
        blocks = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
        self.assertEqual(agent_worker.summarize_tool_result(blocks), "first second")

    def test_a_block_list_of_objects_is_flattened(self):
        self.assertEqual(agent_worker.summarize_tool_result([_Block(text="only")]), "only")

    def test_a_block_with_content_instead_of_text(self):
        self.assertEqual(agent_worker.summarize_tool_result([{"content": "body"}]), "body")

    def test_a_long_result_is_truncated(self):
        self.assertIn("more chars", agent_worker.summarize_tool_result("z" * 2000))


class RenderBlockTestCase(unittest.TestCase):
    def test_a_text_block_renders_verbatim(self):
        self.assertEqual(agent_worker.render_block(_Block(text="hello")), ["hello"])

    def test_a_thinking_block_is_labelled(self):
        rendered = agent_worker.render_block(_Block(thinking="planning the decomposition"))
        self.assertIn("[thinking] planning the decomposition", rendered[0])

    def test_a_tool_use_block_shows_the_tool_and_its_input(self):
        block = _Block(name="Bash", input={"command": "pytest -q"})
        self.assertEqual(agent_worker.render_block(block), ["* Bash  pytest -q"])

    def test_a_tool_result_block_is_indented_under_its_call(self):
        block = _Block(tool_use_id="t1", content="3 passed", is_error=False)
        self.assertEqual(agent_worker.render_block(block), ["    -> 3 passed"])

    def test_a_failed_tool_result_is_marked(self):
        block = _Block(tool_use_id="t1", content="permission denied", is_error=True)
        self.assertEqual(agent_worker.render_block(block), ["    !! permission denied"])

    def test_an_unrecognized_block_renders_nothing(self):
        self.assertEqual(agent_worker.render_block(_Block(other="x")), [])


class RenderTestCase(unittest.TestCase):
    class _Message:
        """Stand-in for an SDK message with explicit content blocks."""

        def __init__(self, content=None, result=None, permission_denials=None):
            """Take content blocks, an optional result, and optional denials."""
            self.content = content or []
            if result is not None:
                self.result = result
            if permission_denials is not None:
                self.permission_denials = permission_denials

    def test_text_blocks_are_rendered(self):
        message = self._Message(content=[_Block(text="hello")])
        self.assertEqual(agent_worker.render(message), "hello")

    def test_a_tool_call_shows_what_it_is_doing(self):
        message = self._Message(content=[_Block(name="Write", input={"file_path": "a.py"})])
        self.assertEqual(agent_worker.render(message), "* Write  a.py")

    def test_a_call_and_its_result_read_as_a_pair(self):
        message = self._Message(content=[
            _Block(name="Bash", input={"command": "ls"}),
            _Block(tool_use_id="t", content="a.py", is_error=False),
        ])
        self.assertEqual(agent_worker.render(message), "* Bash  ls\n    -> a.py")

    def test_a_result_message_is_rendered(self):
        self.assertIn("done", agent_worker.render(self._Message(result="done")))

    def test_a_permission_denial_is_surfaced(self):
        # The most important thing to see: the policy stopped the agent, and
        # whoever is watching may want to steer instead of waiting.
        message = self._Message(permission_denials=[{"tool_name": "WebFetch"}])
        self.assertIn("!! denied: WebFetch", agent_worker.render(message))

    def test_a_denial_without_a_tool_name_still_renders(self):
        message = self._Message(permission_denials=["something odd"])
        self.assertIn("denied:", agent_worker.render(message))

    def test_an_empty_message_renders_empty(self):
        self.assertEqual(agent_worker.render(self._Message()), "")

    def test_blank_lines_are_dropped(self):
        message = self._Message(content=[_Block(text="   "), _Block(text="kept")])
        self.assertEqual(agent_worker.render(message), "kept")


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


class _Block:
    """Stand-in for an SDK content block."""

    def __init__(self, **kwargs):
        """Take whatever attributes the test needs."""
        self.__dict__.update(kwargs)


class _Msg:
    """Stand-in for an SDK message."""

    def __init__(self, text=None, result=None):
        """Build a text message, a result message, or an empty one."""
        self.content = [_Block(text=text)] if text else []
        if result is not None:
            self.result = result


class _FakeClient:
    """Stand-in for ClaudeSDKClient: scripted responses, recorded queries."""

    def __init__(self, responses):
        """*responses* is one list of messages per expected turn."""
        self._responses = list(responses)
        self.queries = []
        self.interrupted = 0

    async def __aenter__(self):
        """Enter the async context, as the real client does."""
        return self

    async def __aexit__(self, *exc):
        """Leave the async context."""
        return False

    async def query(self, prompt, session_id="default"):
        """Record a turn's prompt."""
        self.queries.append(prompt)

    async def interrupt(self):
        """Record an interrupt request."""
        self.interrupted += 1

    async def receive_response(self):
        """Yield the next scripted turn's messages."""
        for message in (self._responses.pop(0) if self._responses else []):
            yield message


def _patch_client(client):
    """Patch the worker's ClaudeSDKClient with a scripted fake."""
    return patch.object(agent_worker, "ClaudeSDKClient", lambda options: client)


def _control(job_dir):
    """Create and return the job's control directory."""
    path = os.path.join(job_dir, agent_worker.CONTROL_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def _queue_steer(job_dir, *messages):
    """Append steering messages the way the portal does."""
    with open(os.path.join(_control(job_dir), agent_worker.STEER_FILENAME), "a", encoding="utf-8") as h:
        for message in messages:
            h.write(json.dumps({"message": message}) + "\n")


def _request_stop(job_dir):
    """Write the stop file the way the portal does."""
    open(os.path.join(_control(job_dir), agent_worker.STOP_FILENAME), "w").close()


class SessionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = self.tmp.name
        _control(self.job)

    def _run(self, client):
        with _patch_client(client):
            return asyncio.run(agent_worker.run_session(self.job, "go", "m"))

    def _transcript(self):
        with open(os.path.join(self.job, agent_worker.TRANSCRIPT_NAME), encoding="utf-8") as handle:
            return handle.read()

    def test_the_transcript_is_streamed_to_disk(self):
        outcome = self._run(_FakeClient([[_Msg("first"), _Msg("second")]]))
        self.assertEqual(outcome["turns"], 2)
        self.assertIn("first", self._transcript())
        self.assertIn("second", self._transcript())

    def test_the_final_result_is_captured_as_the_summary(self):
        outcome = self._run(_FakeClient([[_Msg(result="authored 3 nodes")]]))
        self.assertEqual(outcome["summary"], "authored 3 nodes")

    def test_a_session_with_no_steering_runs_exactly_one_turn(self):
        client = _FakeClient([[_Msg("done")]])
        outcome = self._run(client)
        self.assertEqual(client.queries, ["go"])
        self.assertEqual(outcome["steers"], 0)
        self.assertFalse(outcome["stopped"])

    def test_a_queued_instruction_becomes_the_next_turn(self):
        _queue_steer(self.job, "focus on CA3 only")
        client = _FakeClient([[_Msg("first pass")], [_Msg("adjusted")]])
        outcome = self._run(client)
        self.assertEqual(outcome["steers"], 1)
        self.assertEqual(len(client.queries), 2)
        self.assertIn("focus on CA3 only", client.queries[1])

    def test_steering_is_framed_as_an_operator_note_not_as_data(self):
        _queue_steer(self.job, "ignore vis2")
        client = _FakeClient([[_Msg("a")], [_Msg("b")]])
        self._run(client)
        self.assertIn("live instruction", client.queries[1])
        self.assertIn("does not replace the outbox contract", client.queries[1])

    def test_steering_appears_in_the_transcript(self):
        _queue_steer(self.job, "narrow the claim")
        self._run(_FakeClient([[_Msg("a")], [_Msg("b")]]))
        self.assertIn("[steering: narrow the claim]", self._transcript())

    def test_the_same_instruction_is_not_replayed_on_later_turns(self):
        _queue_steer(self.job, "one")
        client = _FakeClient([[_Msg("a")], [_Msg("b")], [_Msg("c")]])
        outcome = self._run(client)
        self.assertEqual(outcome["steers"], 1)
        self.assertEqual(len(client.queries), 2)

    def test_several_instructions_are_delivered_together(self):
        _queue_steer(self.job, "first", "second")
        client = _FakeClient([[_Msg("a")], [_Msg("b")]])
        outcome = self._run(client)
        self.assertEqual(outcome["steers"], 2)
        self.assertIn("first", client.queries[1])
        self.assertIn("second", client.queries[1])

    def test_a_stop_request_before_the_first_turn_ends_the_session(self):
        _request_stop(self.job)
        client = _FakeClient([[_Msg("a")], [_Msg("b")]])
        outcome = self._run(client)
        self.assertTrue(outcome["stopped"])
        self.assertEqual(len(client.queries), 1)
        self.assertIn("stopped at the operator's request", self._transcript())

    def test_a_stop_request_mid_turn_interrupts_the_session(self):
        _request_stop(self.job)
        client = _FakeClient([[_Msg("a"), _Msg("b")]])
        outcome = self._run(client)
        self.assertTrue(outcome["stopped"])
        self.assertEqual(client.interrupted, 1)

    def test_a_stop_request_wins_over_queued_steering(self):
        _queue_steer(self.job, "keep going")
        _request_stop(self.job)
        client = _FakeClient([[_Msg("a")], [_Msg("b")]])
        outcome = self._run(client)
        self.assertTrue(outcome["stopped"])
        self.assertEqual(len(client.queries), 1)


class SteerFileTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = self.tmp.name
        _control(self.job)

    def test_a_missing_steer_file_yields_nothing(self):
        self.assertEqual(agent_worker.drain_steering(self.job, 0), [])

    def test_only_messages_past_the_consumed_count_are_returned(self):
        _queue_steer(self.job, "a", "b", "c")
        self.assertEqual(agent_worker.drain_steering(self.job, 2), ["c"])

    def test_a_malformed_line_is_skipped(self):
        path = os.path.join(_control(self.job), agent_worker.STEER_FILENAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json\n")
            handle.write(json.dumps({"message": "good"}) + "\n")
            handle.write(json.dumps({"no_message": 1}) + "\n")
        self.assertEqual(agent_worker.drain_steering(self.job, 0), ["good"])

    def test_blank_lines_do_not_count_as_messages(self):
        path = os.path.join(_control(self.job), agent_worker.STEER_FILENAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n\n" + json.dumps({"message": "only"}) + "\n")
        self.assertEqual(agent_worker.drain_steering(self.job, 0), ["only"])

    def test_stop_is_detected_only_once_requested(self):
        self.assertFalse(agent_worker.stop_requested(self.job))
        _request_stop(self.job)
        self.assertTrue(agent_worker.stop_requested(self.job))


if __name__ == "__main__":
    unittest.main()
