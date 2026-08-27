"""Tests for the verification runner: hashing, code gates, and the sandbox."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
import subprocess
from unittest.mock import MagicMock, patch

from aind_metadata_viz.verification import runner, sandbox


def _lock():
    return b"pytest==8.0.0\n"


def _files(**overrides):
    files = {
        "analysis.py": b"def main(data_dir):\n    return {'holds': True}\n",
        "test_analysis.py": b"def test_main():\n    pass\n",
        "known_cases.json": b'[{"name": "positive", "input": null, "expected": {"holds": true}}]',
        "environment.lock": _lock(),
    }
    files.update(overrides)
    return {k: v for k, v in files.items() if v is not None}


class HashingTestCase(unittest.TestCase):
    def test_canonical_json_is_order_independent(self):
        self.assertEqual(runner.canonical_json({"b": 1, "a": 2}), runner.canonical_json({"a": 2, "b": 1}))

    def test_equal_results_hash_equally(self):
        self.assertEqual(runner.result_hash({"p": 0.5}), runner.result_hash({"p": 0.5}))

    def test_different_results_hash_differently(self):
        self.assertNotEqual(runner.result_hash({"p": 0.5}), runner.result_hash({"p": 0.6}))

    def test_code_hash_covers_analysis_and_the_lock_file(self):
        base = runner.code_hash(_files())
        self.assertNotEqual(base, runner.code_hash(_files(**{"analysis.py": b"changed"})))
        self.assertNotEqual(base, runner.code_hash(_files(**{"environment.lock": b"numpy==2\n"})))

    def test_code_hash_ignores_the_test_file(self):
        self.assertEqual(
            runner.code_hash(_files()),
            runner.code_hash(_files(**{"test_analysis.py": b"# different\n"})),
        )

    def test_code_hash_tolerates_a_missing_file(self):
        self.assertIsInstance(runner.code_hash({}), str)


class CodeLayoutTestCase(unittest.TestCase):
    def test_a_complete_sidecar_passes(self):
        gates = runner.check_code_layout(_files())
        self.assertTrue(gates["ok"])
        self.assertEqual(gates["known_cases"], 1)

    def test_a_missing_required_file_fails(self):
        gates = runner.check_code_layout(_files(**{"test_analysis.py": None}))
        self.assertFalse(gates["ok"])
        self.assertIn("test_analysis.py", gates["missing"])

    def test_an_empty_known_cases_list_fails(self):
        gates = runner.check_code_layout(_files(**{"known_cases.json": b"[]"}))
        self.assertFalse(gates["ok"])
        self.assertIn("at least one case", " ".join(gates["errors"]))

    def test_known_cases_must_be_a_list(self):
        gates = runner.check_code_layout(_files(**{"known_cases.json": b'{"a": 1}'}))
        self.assertIn("must be a list", " ".join(gates["errors"]))

    def test_unparseable_known_cases_fail(self):
        gates = runner.check_code_layout(_files(**{"known_cases.json": b"{not json"}))
        self.assertIn("not valid JSON", " ".join(gates["errors"]))

    def test_an_empty_lock_file_fails(self):
        gates = runner.check_code_layout(_files(**{"environment.lock": b"   \n"}))
        self.assertIn("must be pinned", " ".join(gates["errors"]))

    def test_an_empty_sidecar_reports_every_required_file(self):
        self.assertEqual(len(runner.check_code_layout({})["missing"]), 4)


class JobDirectoryTestCase(unittest.TestCase):
    def test_a_sidecar_is_written_into_a_fresh_job_directory(self):
        with tempfile.TemporaryDirectory() as root:
            job_dir = runner.materialize_job("stmt-a", _files(), root=root)
            self.assertTrue(os.path.isfile(os.path.join(job_dir, "code", "analysis.py")))
            self.assertTrue(os.path.isdir(os.path.join(job_dir, "data")))

    def test_nested_sidecar_paths_are_created(self):
        with tempfile.TemporaryDirectory() as root:
            job_dir = runner.materialize_job("stmt-a", {"tests/test_x.py": b"x"}, root=root)
            self.assertTrue(os.path.isfile(os.path.join(job_dir, "code", "tests", "test_x.py")))


class DataUrlTestCase(unittest.TestCase):
    def test_a_partitioned_table_url_names_the_asset(self):
        url = runner.data_url({"table": "platform_swdb_trials", "asset_name": "660023_2023-08-08"}, "bdc-v0.40")
        self.assertTrue(url.endswith("/bdc-v0.40/platform_swdb_trials/asset_name=660023_2023-08-08/data.pqt"))

    def test_an_unpartitioned_table_url_has_no_asset_segment(self):
        url = runner.data_url({"table": "platform_swdb_sessions"}, "bdc-v0.40")
        self.assertTrue(url.endswith("/bdc-v0.40/platform_swdb_sessions.pqt"))

    def test_a_reference_can_pin_its_own_cache_version(self):
        url = runner.data_url({"table": "t", "version": "bdc-v0.39"}, "bdc-v0.40")
        self.assertIn("bdc-v0.39", url)


class _FakeResponse(io.BytesIO):
    """Minimal stand-in for urlopen's context-managed response."""

    def __enter__(self):
        """Return itself, as urlopen's response does."""
        return self

    def __exit__(self, *exc):
        """Close on exit."""
        self.close()
        return False


class CacheVersionTestCase(unittest.TestCase):
    def test_the_newest_version_is_chosen_numerically(self):
        def opener(url, timeout=None):
            return _FakeResponse(json.dumps(["bdc-v0.9", "bdc-v0.40", "bdc-v0.10"]).encode())

        self.assertEqual(runner.resolve_cache_version(opener=opener), "bdc-v0.40")

    def test_an_empty_version_index_is_an_error(self):
        def opener(url, timeout=None):
            return _FakeResponse(b"[]")

        with self.assertRaises(runner.RunnerError):
            runner.resolve_cache_version(opener=opener)


class DownloadTestCase(unittest.TestCase):
    def test_a_reference_lands_at_its_cache_relative_path(self):
        def opener(url, timeout=None):
            return _FakeResponse(b"PARQUET")

        with tempfile.TemporaryDirectory() as dest:
            manifest = runner.download_data(
                [{"table": "platform_swdb_trials", "asset_name": "a1"}], dest, "bdc-v0.40", opener=opener
            )
            self.assertEqual(manifest[0]["path"], "platform_swdb_trials/asset_name=a1/data.pqt")
            self.assertEqual(manifest[0]["bytes"], 7)
            self.assertTrue(os.path.isfile(os.path.join(dest, manifest[0]["path"])))

    def test_an_unreachable_reference_is_a_runner_error(self):
        def opener(url, timeout=None):
            raise OSError("no route to host")

        with tempfile.TemporaryDirectory() as dest:
            with self.assertRaises(runner.RunnerError):
                runner.download_data([{"table": "t", "asset_name": "a"}], dest, "v", opener=opener)

    def test_an_oversized_download_is_refused(self):
        def opener(url, timeout=None):
            return _FakeResponse(b"x" * (runner.MAX_DOWNLOAD_BYTES + 1))

        with tempfile.TemporaryDirectory() as dest:
            with self.assertRaises(runner.RunnerError):
                runner.download_data([{"table": "t", "asset_name": "a"}], dest, "v", opener=opener)

    def test_no_references_downloads_nothing(self):
        with tempfile.TemporaryDirectory() as dest:
            self.assertEqual(runner.download_data([], dest, "v"), [])


class ResultParsingTestCase(unittest.TestCase):
    def test_the_result_is_read_from_after_the_marker(self):
        output = "noise\n<<<VGRAPH_RESULT>>>\n{\"holds\": true}\n"
        self.assertEqual(runner.parse_result(output), {"holds": True})

    def test_output_without_a_marker_yields_nothing(self):
        self.assertIsNone(runner.parse_result("just logs"))

    def test_a_malformed_result_yields_nothing(self):
        self.assertIsNone(runner.parse_result("<<<VGRAPH_RESULT>>>\n{not json\n"))

    def test_an_empty_result_yields_nothing(self):
        self.assertIsNone(runner.parse_result("<<<VGRAPH_RESULT>>>\n"))


class AxisEvaluationTestCase(unittest.TestCase):
    def test_a_first_reproducible_run_records_its_hash(self):
        passed, note = runner.evaluate_axis("reproducible", {}, {"holds": True}, None)
        self.assertTrue(passed)
        self.assertIn("first run", note)

    def test_a_matching_hash_passes_reproducibility(self):
        value = {"holds": True}
        passed, note = runner.evaluate_axis("reproducible", {}, value, runner.result_hash(value))
        self.assertTrue(passed)
        self.assertIn("matches", note)

    def test_a_changed_result_fails_reproducibility(self):
        passed, note = runner.evaluate_axis("reproducible", {}, {"holds": True}, "0" * 64)
        self.assertFalse(passed)
        self.assertIn("changed", note)

    def test_a_missing_result_fails_any_axis(self):
        passed, note = runner.evaluate_axis("reproducible", {}, None, None)
        self.assertFalse(passed)
        self.assertIn("no parseable result", note)

    def test_the_other_axes_read_the_holds_field(self):
        self.assertTrue(runner.evaluate_axis("replicable", {}, {"holds": True}, None)[0])
        self.assertFalse(runner.evaluate_axis("robust", {}, {"holds": False}, None)[0])

    def test_the_other_axes_require_a_holds_field(self):
        passed, note = runner.evaluate_axis("generalizable", {}, {"p": 0.1}, None)
        self.assertFalse(passed)
        self.assertIn("'holds'", note)


class ApplyRunTestCase(unittest.TestCase):
    def _record(self, passed=True, axis="reproducible", stage="complete"):
        return {
            "axis": axis, "passed": passed, "stage": stage, "note": "n",
            "code_hash": "abc", "env": "environment.lock", "result_hash": "def",
            "ran_at": "2026-08-26T00:00:00Z", "log_prefix": "runs/stmt-a/t",
        }

    def test_a_passing_run_marks_the_axis_passed(self):
        node = {"id": "stmt-a"}
        runner.apply_run(node, self._record())
        self.assertEqual(node["verification"]["reproducible"]["status"], "passed")
        self.assertEqual(node["verification"]["reproducible"]["run"]["result_hash"], "def")

    def test_a_failing_run_marks_the_axis_failed(self):
        node = {"id": "stmt-a", "status": "verified"}
        runner.apply_run(node, self._record(passed=False, stage="analysis"))
        self.assertEqual(node["verification"]["reproducible"]["status"], "failed")
        self.assertEqual(node["status"], "failed")

    def test_a_failure_before_the_analysis_leaves_the_node_status_alone(self):
        node = {"id": "stmt-a", "status": "verified"}
        runner.apply_run(node, self._record(passed=False, stage="gates"))
        self.assertEqual(node["status"], "verified")

    def test_a_previous_run_is_kept_in_the_history(self):
        node = {"id": "stmt-a"}
        runner.apply_run(node, self._record())
        runner.apply_run(node, self._record(passed=False))
        self.assertEqual(len(node["verification"]["reproducible"]["runs"]), 1)

    def test_a_non_reproducible_axis_never_changes_the_node_status(self):
        node = {"id": "stmt-a", "status": "verified"}
        runner.apply_run(node, self._record(passed=False, axis="robust", stage="analysis"))
        self.assertEqual(node["status"], "verified")


class StalenessTestCase(unittest.TestCase):
    def test_a_changed_sidecar_is_stale(self):
        node = {"verification": {"reproducible": {"run": {"code_hash": "old"}}}}
        self.assertTrue(runner.code_is_stale(node, _files()))

    def test_an_unchanged_sidecar_is_not_stale(self):
        files = _files()
        node = {"verification": {"reproducible": {"run": {"code_hash": runner.code_hash(files)}}}}
        self.assertFalse(runner.code_is_stale(node, files))

    def test_a_never_run_node_is_not_stale(self):
        self.assertFalse(runner.code_is_stale({}, _files()))


class SandboxTestCase(unittest.TestCase):
    def test_credentials_are_stripped_from_the_child_environment(self):
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "shh", "BEDROCK_ROLE_ARN": "arn:x"}):
            env = sandbox.sandbox_env()
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("BEDROCK_ROLE_ARN", env)

    def test_extras_are_added_back_after_the_scrub(self):
        env = sandbox.sandbox_env({"AWS_PROFILE": "bedrock-access"})
        self.assertEqual(env["AWS_PROFILE"], "bedrock-access")

    def test_the_child_gets_a_deterministic_hash_seed(self):
        self.assertEqual(sandbox.sandbox_env()["PYTHONHASHSEED"], "0")

    def test_a_command_runs_and_reports_its_output(self):
        result = sandbox.run_sandboxed([sys.executable, "-c", "print('hi')"], cwd=".", timeout=60)
        self.assertTrue(result.ok)
        self.assertIn("hi", result.output)

    def test_a_nonzero_exit_is_not_ok(self):
        result = sandbox.run_sandboxed([sys.executable, "-c", "raise SystemExit(3)"], cwd=".", timeout=60)
        self.assertEqual(result.returncode, 3)
        self.assertFalse(result.ok)

    def test_a_hanging_command_times_out(self):
        result = sandbox.run_sandboxed(
            [sys.executable, "-c", "import time; time.sleep(30)"], cwd=".", timeout=1
        )
        self.assertTrue(result.timed_out)
        self.assertFalse(result.ok)

    def test_a_timeout_kills_the_whole_process_group(self):
        # The child spawns children of its own (the Agent SDK launches the
        # bundled CLI, the runner launches pytest). Killing only the direct
        # child leaves those running and holding the output pipe, which used
        # to block the reap past the timeout.
        marker = os.path.join(tempfile.gettempdir(), "vgraph_group_test_pid")
        if os.path.exists(marker):
            os.unlink(marker)
        grandchild = f"""
import os, time
open({marker!r}, 'w').write(str(os.getpid()))
time.sleep(120)
"""
        child = f"""
import subprocess, sys, time
subprocess.Popen([sys.executable, '-c', {grandchild!r}])
time.sleep(120)
"""
        started = time.time()
        result = sandbox.run_sandboxed(
            [sys.executable, "-c", child],
            cwd=tempfile.gettempdir(),
            env=sandbox.sandbox_env({"PATH": os.environ.get("PATH", "")}),
            timeout=3,
        )
        elapsed = time.time() - started

        self.assertTrue(result.timed_out)
        self.assertLess(elapsed, 20, "run_sandboxed did not return promptly after its timeout")

        time.sleep(0.5)
        self.assertTrue(os.path.exists(marker), "grandchild never started")
        pid = int(open(marker).read())
        os.unlink(marker)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_killing_a_group_falls_back_to_the_child_when_the_group_is_gone(self):
        # os.getpgid raises once the process has already been reaped; the
        # fallback must not propagate that out of the timeout path.
        process = MagicMock()
        process.pid = 424242
        with patch.object(sandbox.os, "killpg", side_effect=ProcessLookupError):
            sandbox.kill_group(process)
        process.kill.assert_called_once()

    def test_a_group_that_outlives_the_grace_period_stops_being_waited_on(self):
        # A descendant that called setsid escapes the group kill; the job queue
        # must not block on it forever.
        process = MagicMock()
        process.pid = 1
        process.__enter__ = lambda self_: self_
        process.__exit__ = lambda self_, *exc: False
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("cmd", 1),
            subprocess.TimeoutExpired("cmd", 1),
        ]
        with patch.object(sandbox.subprocess, "Popen", return_value=process), \
             patch.object(sandbox, "kill_group") as kill:
            result = sandbox.run_sandboxed(["/bin/true"], cwd=".", timeout=1)
        self.assertTrue(result.timed_out)
        self.assertIn("[timed out]", result.output)
        self.assertEqual(kill.call_count, 2)

    def test_a_missing_binary_is_reported_rather_than_raised(self):
        result = sandbox.run_sandboxed(["/definitely/not/here"], cwd=".", timeout=10)
        self.assertFalse(result.ok)
        self.assertIn("failed to start", result.output)

    def test_a_child_cannot_read_stdin(self):
        result = sandbox.run_sandboxed(
            [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], cwd=".", timeout=60
        )
        self.assertIn("''", result.output)

    def test_long_output_is_truncated(self):
        text = "x" * (sandbox.MAX_OUTPUT_BYTES + 100)
        self.assertIn("truncated", sandbox._truncate(text))

    def test_short_output_is_left_alone(self):
        self.assertEqual(sandbox._truncate("short"), "short")

    def test_a_result_serializes_for_the_run_record(self):
        self.assertEqual(
            sandbox.SandboxResult(0, "out").to_dict(),
            {"returncode": 0, "output": "out", "timed_out": False},
        )

    def test_a_job_directory_is_handed_to_the_sandbox_user(self):
        # In the container the portal creates job directories as root, mode
        # 0700, and the child runs as `vgraph` -- without this it cannot stat
        # its own working directory, let alone read the prompt.
        with tempfile.TemporaryDirectory() as job:
            os.makedirs(os.path.join(job, "outbox", "nodes"))
            open(os.path.join(job, "prompt.txt"), "w").close()
            with patch.object(sandbox, "_sandbox_user_ids", return_value=(4242, 4243)), \
                 patch.object(sandbox.os, "chown") as chown:
                sandbox.grant_to_sandbox_user(job)
        owned = {call.args[0] for call in chown.call_args_list}
        self.assertIn(job, owned)
        self.assertIn(os.path.join(job, "prompt.txt"), owned)
        self.assertIn(os.path.join(job, "outbox", "nodes"), owned)
        self.assertTrue(all(call.args[1:] == (4242, 4243) for call in chown.call_args_list))

    def test_granting_is_a_no_op_when_privileges_are_not_dropped(self):
        with tempfile.TemporaryDirectory() as job:
            with patch.object(sandbox, "_sandbox_user_ids", return_value=None), \
                 patch.object(sandbox.os, "chown") as chown:
                sandbox.grant_to_sandbox_user(job)
        chown.assert_not_called()

    def test_on_start_receives_the_live_process(self):
        seen = []
        result = sandbox.run_sandboxed(
            [sys.executable, "-c", "print('hi')"], cwd=".", timeout=60, on_start=seen.append
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(seen[0].pid)

    def test_the_sandbox_user_is_skipped_when_it_does_not_exist(self):
        with patch.object(sandbox, "SANDBOX_USER", "definitely-not-a-user"):
            self.assertIsNone(sandbox._sandbox_user_ids())

    def test_the_sandbox_user_is_skipped_when_it_is_the_current_user(self):
        import pwd

        with patch.object(sandbox, "SANDBOX_USER", pwd.getpwuid(os.getuid()).pw_name):
            self.assertIsNone(sandbox._sandbox_user_ids())

    def test_privileges_are_only_dropped_when_running_as_root(self):
        record = type("R", (), {"pw_uid": 999, "pw_gid": 999})()
        with patch("pwd.getpwnam", return_value=record):
            with patch.object(os, "getuid", return_value=1000):
                self.assertIsNone(sandbox._sandbox_user_ids())
            with patch.object(os, "getuid", return_value=0):
                self.assertEqual(sandbox._sandbox_user_ids(), (999, 999))


class VerifyNodeTestCase(unittest.TestCase):
    def test_a_malformed_sidecar_stops_before_any_execution(self):
        record = runner.verify_node({"id": "stmt-a"}, {}, axis="reproducible")
        self.assertFalse(record["passed"])
        self.assertEqual(record["stage"], "layout")
        self.assertFalse(record["layout"]["ok"])

    def test_an_unreachable_data_cache_fails_the_run_honestly(self):
        def opener(url, timeout=None):
            raise OSError("offline")

        with tempfile.TemporaryDirectory() as root:
            record = runner.verify_node(
                {"id": "stmt-a", "data": []}, _files(), job_root=root, opener=opener
            )
        self.assertFalse(record["passed"])
        self.assertEqual(record["stage"], "data")
        self.assertIn("offline", record["note"])

    def test_a_failed_environment_build_stops_before_the_gates(self):
        def opener(url, timeout=None):
            return _FakeResponse(json.dumps(["bdc-v0.40"]).encode())

        with tempfile.TemporaryDirectory() as root:
            with patch.object(runner, "ensure_venv", return_value=("/nope", sandbox.SandboxResult(1, "boom"))):
                record = runner.verify_node(
                    {"id": "stmt-a", "data": []}, _files(), job_root=root, opener=opener
                )
        self.assertEqual(record["stage"], "environment")
        self.assertIn("pinned environment", record["note"])

    def test_failing_gates_stop_before_the_analysis(self):
        def opener(url, timeout=None):
            return _FakeResponse(json.dumps(["bdc-v0.40"]).encode())

        gates = {"tests": {"output": "red"}, "known_cases": {"output": ""}, "ok": False}
        with tempfile.TemporaryDirectory() as root:
            with patch.object(runner, "ensure_venv", return_value=("py", sandbox.SandboxResult(0, ""))), \
                 patch.object(runner, "run_gates", return_value=gates):
                record = runner.verify_node(
                    {"id": "stmt-a", "data": []}, _files(), job_root=root, opener=opener
                )
        self.assertEqual(record["stage"], "gates")
        self.assertIn("code gates failed", record["note"])

    def test_a_clean_run_records_a_result_hash(self):
        def opener(url, timeout=None):
            return _FakeResponse(json.dumps(["bdc-v0.40"]).encode())

        gates = {"tests": {"output": ""}, "known_cases": {"output": ""}, "ok": True}
        with tempfile.TemporaryDirectory() as root:
            with patch.object(runner, "ensure_venv", return_value=("py", sandbox.SandboxResult(0, ""))), \
                 patch.object(runner, "run_gates", return_value=gates), \
                 patch.object(runner, "run_analysis",
                              return_value=(sandbox.SandboxResult(0, ""), {"holds": True})):
                record = runner.verify_node(
                    {"id": "stmt-a", "data": []}, _files(), job_root=root, opener=opener
                )
        self.assertTrue(record["passed"])
        self.assertEqual(record["stage"], "complete")
        self.assertEqual(record["result_hash"], runner.result_hash({"holds": True}))

    def test_an_analysis_that_crashes_fails_the_run(self):
        def opener(url, timeout=None):
            return _FakeResponse(json.dumps(["bdc-v0.40"]).encode())

        gates = {"tests": {"output": ""}, "known_cases": {"output": ""}, "ok": True}
        with tempfile.TemporaryDirectory() as root:
            with patch.object(runner, "ensure_venv", return_value=("py", sandbox.SandboxResult(0, ""))), \
                 patch.object(runner, "run_gates", return_value=gates), \
                 patch.object(runner, "run_analysis",
                              return_value=(sandbox.SandboxResult(1, "traceback"), None)):
                record = runner.verify_node(
                    {"id": "stmt-a", "data": []}, _files(), job_root=root, opener=opener
                )
        self.assertFalse(record["passed"])
        self.assertIn("did not exit cleanly", record["note"])


class VenvTestCase(unittest.TestCase):
    def test_an_existing_venv_is_reused(self):
        with tempfile.TemporaryDirectory() as root:
            import hashlib

            digest = hashlib.sha256(b"pinned\n").hexdigest()[:16]
            os.makedirs(os.path.join(root, digest, "bin"))
            open(os.path.join(root, digest, "bin", "python"), "w").close()
            python, result = runner.ensure_venv("pinned\n", root=root)
            self.assertIn("cache hit", result.output)
            self.assertTrue(python.endswith("bin/python"))

    def test_a_failed_creation_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(runner, "run_sandboxed", return_value=sandbox.SandboxResult(1, "no venv module")):
                _python, result = runner.ensure_venv("pinned\n", root=root)
            self.assertFalse(result.ok)

    def test_a_failed_install_removes_the_half_built_venv(self):
        with tempfile.TemporaryDirectory() as root:
            calls = [sandbox.SandboxResult(0, "created"), sandbox.SandboxResult(1, "pip failed")]
            with patch.object(runner, "run_sandboxed", side_effect=calls):
                _python, result = runner.ensure_venv("pinned\n", root=root)
            self.assertFalse(result.ok)


class RunGatesTestCase(unittest.TestCase):
    def test_both_gates_must_pass(self):
        with patch.object(runner, "run_sandboxed",
                          side_effect=[sandbox.SandboxResult(0, "green"), sandbox.SandboxResult(0, "1 case")]):
            self.assertTrue(runner.run_gates("py", ".")["ok"])

    def test_a_failing_known_case_fails_the_gates(self):
        with patch.object(runner, "run_sandboxed",
                          side_effect=[sandbox.SandboxResult(0, "green"), sandbox.SandboxResult(1, "mismatch")]):
            self.assertFalse(runner.run_gates("py", ".")["ok"])


class RunAnalysisTestCase(unittest.TestCase):
    def test_the_result_is_parsed_out_of_the_output(self):
        with patch.object(runner, "run_sandboxed",
                          return_value=sandbox.SandboxResult(0, '<<<VGRAPH_RESULT>>>\n{"holds": true}\n')):
            outcome, value = runner.run_analysis("py", ".", "data")
        self.assertTrue(outcome.ok)
        self.assertEqual(value, {"holds": True})


if __name__ == "__main__":
    unittest.main()
