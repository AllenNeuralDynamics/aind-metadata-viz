"""Tests for the agent job directory, the outbox contract, and the job queue."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from aind_metadata_viz.verification import agent, jobs, sandbox


MANIFEST = [{"id": "ent-unit", "kind": "entity", "label": "Unit 1", "status": None, "updated": None}]


class JobDirectoryTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.job = agent.AgentJob(
            "agent-1", "Verify that 30% of CA3 units respond to vis1", MANIFEST, root=self.root.name
        )

    def test_all_four_skills_are_written(self):
        skills_dir = os.path.join(self.job.dir, ".claude", "skills")
        self.assertEqual(
            sorted(os.listdir(skills_dir)),
            ["dynamic-routing-data", "graph-schema", "node-authoring", "recursive-verification"],
        )

    def test_each_skill_carries_frontmatter_the_sdk_can_read(self):
        path = os.path.join(self.job.dir, ".claude", "skills", "graph-schema", "SKILL.md")
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
        self.assertTrue(body.startswith("---\nname: graph-schema\n"))
        self.assertIn("description:", body)

    def test_the_manifest_is_exported_for_reuse_search(self):
        with open(os.path.join(self.job.dir, "manifest.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), MANIFEST)

    def test_the_outbox_starts_empty(self):
        self.assertEqual(os.listdir(os.path.join(self.job.dir, "outbox", "nodes")), [])

    def test_the_request_is_recorded_verbatim(self):
        with open(os.path.join(self.job.dir, "request.md"), encoding="utf-8") as handle:
            self.assertIn("CA3", handle.read())

    def test_the_prompt_points_the_agent_at_the_skills_and_the_outbox(self):
        prompt = self.job.prompt()
        self.assertIn(".claude/skills/", prompt)
        self.assertIn("outbox/", prompt)
        self.assertIn("CA3", prompt)

    def test_cleanup_removes_the_directory(self):
        self.job.cleanup()
        self.assertFalse(os.path.exists(self.job.dir))

    def test_running_records_the_transcript(self):
        with patch.object(agent, "run_sandboxed", return_value=sandbox.SandboxResult(0, "agent output")):
            result = self.job.run()
        self.assertEqual(result["returncode"], 0)
        self.assertIn("agent output", self.job.transcript())

    def test_the_worker_is_run_by_path_not_as_a_package_module(self):
        # `python -m` would import the verification package first, and its
        # __init__ pulls in the whole portal app -- which the worker does not
        # need and which cannot even be imported inside the sandbox.
        command = self.job.command()
        self.assertEqual(command, [sys.executable, agent.AGENT_WORKER_PATH, self.job.dir])
        self.assertNotIn("-m", command)
        self.assertTrue(agent.AGENT_WORKER_PATH.endswith("agent_worker.py"))

    def test_the_prompt_is_handed_over_on_disk_not_on_argv(self):
        # argv is world-readable via the process table; the prompt carries the
        # user's request text, so it goes to a file inside the job directory.
        self.assertNotIn(self.job.prompt(), self.job.command())
        with open(os.path.join(self.job.dir, "prompt.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), self.job.prompt())

    def test_the_model_is_passed_to_the_worker_in_the_environment(self):
        with patch.object(agent, "run_sandboxed", return_value=sandbox.SandboxResult(0, "")) as run:
            self.job.run()
        self.assertEqual(run.call_args.kwargs["env"]["VGRAPH_AGENT_MODEL"], agent.AGENT_MODEL)

    def test_the_default_model_is_a_cross_region_bedrock_profile(self):
        # Claude Sonnet 5 has no in-Region inference on bedrock-runtime, so a
        # bare `anthropic.claude-sonnet-5` would not resolve; the id must carry
        # one of Bedrock's geo/global CRIS prefixes.
        self.assertRegex(agent.AGENT_MODEL, r"^(us|eu|au|global)\.anthropic\.")

    def test_each_job_gets_a_private_config_home(self):
        with patch.object(agent, "run_sandboxed", return_value=sandbox.SandboxResult(0, "")) as run:
            self.job.run()
        self.assertEqual(run.call_args.kwargs["env"]["HOME"], self.job.dir)

    def test_the_config_home_does_not_outlive_the_job(self):
        job_dir = self.job.dir
        self.job.cleanup()
        self.assertFalse(os.path.exists(job_dir))


class LiveControlTestCase(unittest.TestCase):
    """Cancelling and steering a session that is already running."""

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.job = agent.AgentJob("agent-live", "Verify CA3 units", [], root=self.root.name)

    def _steer_lines(self):
        path = os.path.join(self.job.control_dir, agent.STEER_FILENAME)
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_the_control_directory_is_scaffolded(self):
        self.assertTrue(os.path.isdir(self.job.control_dir))

    def test_a_steering_message_is_queued_for_the_worker(self):
        self.job.steer("focus on CA3")
        self.assertEqual(self._steer_lines(), [{"message": "focus on CA3"}])

    def test_steering_messages_accumulate_in_order(self):
        self.job.steer("first")
        self.job.steer("second")
        self.assertEqual([e["message"] for e in self._steer_lines()], ["first", "second"])

    def test_an_empty_steering_message_is_refused(self):
        with self.assertRaises(ValueError):
            self.job.steer("   ")

    def test_an_oversized_steering_message_is_refused(self):
        with self.assertRaises(ValueError):
            self.job.steer("x" * (agent.MAX_STEER_BYTES + 1))

    def test_cancelling_writes_the_stop_file(self):
        self.job.cancel()
        self.assertTrue(os.path.exists(os.path.join(self.job.control_dir, agent.STOP_FILENAME)))
        self.assertTrue(self.job.cancelled)

    def test_cancelling_before_the_process_starts_reports_nothing_signalled(self):
        self.assertFalse(self.job.cancel())

    def test_cancelling_kills_the_live_process_group(self):
        process = MagicMock()
        process.poll.return_value = None
        self.job._register_process(process)
        with patch.object(agent, "kill_group") as kill:
            self.assertTrue(self.job.cancel())
        kill.assert_called_once_with(process)

    def test_cancelling_an_already_finished_process_signals_nothing(self):
        process = MagicMock()
        process.poll.return_value = 0
        self.job._register_process(process)
        with patch.object(agent, "kill_group") as kill:
            self.assertFalse(self.job.cancel())
        kill.assert_not_called()

    def test_a_job_cancelled_before_spawning_is_killed_on_arrival(self):
        # Cancel can land between queueing and the process actually starting;
        # the session must not run on regardless.
        self.job.cancel()
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(agent, "kill_group") as kill:
            self.job._register_process(process)
        kill.assert_called_once_with(process)

    def test_the_run_registers_its_process_for_cancellation(self):
        # Assert the wiring by exercising it: whatever the run hands to
        # on_start must become the process cancel() then signals.
        process = MagicMock()
        process.poll.return_value = None

        def fake_run(command, cwd, env, timeout, on_start=None):
            on_start(process)
            return sandbox.SandboxResult(0, "")

        with patch.object(agent, "run_sandboxed", fake_run):
            self.job.run()
        with patch.object(agent, "kill_group") as kill:
            self.assertTrue(self.job.cancel())
        kill.assert_called_once_with(process)


class SandboxCredentialTestCase(unittest.TestCase):
    """The worker gets Bedrock-scoped, short-lived keys and nothing else."""

    _ASSUMED = {
        "Credentials": {
            "AccessKeyId": "ASIA-TEMP",
            "SecretAccessKey": "temp-secret",
            "SessionToken": "temp-token",
        }
    }

    def _assume(self):
        """Patch boto3's STS client, returning the mock so calls can be asserted."""
        sts = MagicMock()
        sts.assume_role.return_value = self._ASSUMED
        return patch.object(agent.boto3, "client", return_value=sts), sts

    def test_the_role_is_assumed_in_the_parent_not_delegated_to_the_child(self):
        patcher, sts = self._assume()
        with patch.dict(os.environ, {"BEDROCK_ROLE_ARN": "arn:aws:iam::1:role/bedrock"}), patcher:
            env = agent._bedrock_env()
        sts.assume_role.assert_called_once()
        self.assertEqual(sts.assume_role.call_args.kwargs["RoleArn"], "arn:aws:iam::1:role/bedrock")
        self.assertEqual(env["AWS_ACCESS_KEY_ID"], "ASIA-TEMP")
        self.assertEqual(env["AWS_SESSION_TOKEN"], "temp-token")

    def test_the_child_never_receives_a_path_to_the_task_role(self):
        # The ECS credential URI is the task role, which can reach far more
        # than Bedrock. It must not survive the scrub, and neither may the
        # portal's own secrets.
        patcher, _sts = self._assume()
        hostile = {
            "BEDROCK_ROLE_ARN": "arn:aws:iam::1:role/bedrock",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/task",
            "AWS_SECRET_ACCESS_KEY": "task-role-secret",
            "SESSION_SECRET": "cookie-signing-key",
            "PINPOINT_ENCRYPTION_SECRET": "pinpoint-key",
        }
        with patch.dict(os.environ, hostile), patcher:
            env = sandbox.sandbox_env(agent._bedrock_env())

        self.assertNotIn("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", env)
        self.assertNotIn("AWS_PROFILE", env)
        self.assertNotIn("SESSION_SECRET", env)
        self.assertNotIn("PINPOINT_ENCRYPTION_SECRET", env)
        self.assertNotIn("BEDROCK_ROLE_ARN", env)
        # The only secret present is the temporary one we minted.
        self.assertEqual(env["AWS_SECRET_ACCESS_KEY"], "temp-secret")
        self.assertNotIn("task-role-secret", env.values())

    def test_bedrock_mode_is_enabled_for_the_sdk(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(agent._bedrock_env()["CLAUDE_CODE_USE_BEDROCK"], "1")

    def test_no_role_arn_means_no_credentials_are_minted(self):
        with patch.dict(os.environ, {}, clear=True):
            env = agent._bedrock_env()
        self.assertNotIn("AWS_ACCESS_KEY_ID", env)
        self.assertEqual(env["AWS_REGION"], "us-west-2")


class TranscriptTestCase(unittest.TestCase):
    def test_only_the_tail_is_returned(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("a" * 100 + "TAIL")
            path = handle.name
        self.addCleanup(os.unlink, path)
        self.assertEqual(agent.read_transcript(path, tail_bytes=4), "TAIL")

    def test_a_short_transcript_is_returned_whole(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("short")
            path = handle.name
        self.addCleanup(os.unlink, path)
        self.assertEqual(agent.read_transcript(path), "short")

    def test_a_missing_transcript_is_empty(self):
        self.assertEqual(agent.read_transcript("/no/such/file"), "")


def _entity(node_id, entity_type="unit"):
    return {"id": node_id, "kind": "entity", "entity_type": entity_type, "label": node_id}


def _relation():
    return {"id": "rel-r", "kind": "relation", "label": "responds to",
            "signature": {"subject": ["unit"], "object": ["stimulus"]}}


def _statement(node_id, depends_on=()):
    return {"id": node_id, "kind": "statement", "subject": "ent-unit", "relation": "rel-r",
            "object": "ent-stim", "depends_on": list(depends_on)}


class OutboxReadTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.job_dir = self.root.name
        os.makedirs(os.path.join(self.job_dir, "outbox", "nodes"))
        os.makedirs(os.path.join(self.job_dir, "outbox", "code"))

    def _write_node(self, doc, name=None):
        path = os.path.join(self.job_dir, "outbox", "nodes", name or f"{doc['id']}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)

    def _write_code(self, node_id, relpath, data):
        path = os.path.join(self.job_dir, "outbox", "code", node_id, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def test_documents_are_read_from_the_outbox(self):
        self._write_node(_entity("ent-unit"))
        documents, _code, rejected = agent.read_outbox(self.job_dir)
        self.assertEqual([d["id"] for d in documents], ["ent-unit"])
        self.assertEqual(rejected, [])

    def test_one_unparseable_document_does_not_discard_the_rest(self):
        self._write_node(_entity("ent-unit"))
        with open(os.path.join(self.job_dir, "outbox", "nodes", "broken.json"), "w") as handle:
            handle.write("{not json")
        documents, _code, rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(len(documents), 1)
        self.assertIn("unreadable", rejected[0]["reason"])

    def test_non_json_files_are_ignored(self):
        open(os.path.join(self.job_dir, "outbox", "nodes", "notes.txt"), "w").close()
        documents, _code, rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(documents, [])
        self.assertEqual(rejected, [])

    def test_code_sidecars_are_collected_per_node(self):
        self._write_node(_statement("stmt-a"))
        self._write_code("stmt-a", "analysis.py", b"x")
        self._write_code("stmt-a", "tests/test_x.py", b"y")
        _documents, code, _rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(set(code["stmt-a"]), {"analysis.py", os.path.join("tests", "test_x.py")})

    def test_a_node_without_code_gets_an_empty_sidecar(self):
        self._write_node(_entity("ent-unit"))
        _documents, code, _rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(code["ent-unit"], {})

    def test_a_missing_outbox_directory_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(agent.read_outbox(empty)[0], [])

    def test_an_id_that_escapes_the_job_tree_is_rejected_before_any_read(self):
        # The id becomes a path component of the code directory, so a walk
        # must never be started for it. Plant a file where the traversal would
        # land and assert it is not picked up.
        outside = os.path.join(self.job_dir, "secret.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("do not read me")
        self._write_node({"id": "../..", "kind": "entity", "entity_type": "unit", "label": "x"},
                         name="escape.json")

        documents, code, rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(documents, [])
        self.assertEqual(code, {})
        self.assertIn("unsafe node id", rejected[0]["reason"])

    def test_a_document_with_no_id_still_reaches_validation(self):
        self._write_node({"kind": "entity", "entity_type": "unit", "label": "x"}, name="anon.json")
        documents, _code, rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(len(documents), 1)
        self.assertEqual(rejected, [])

    def test_a_symlinked_code_file_is_not_followed(self):
        # A symlink in the outbox could otherwise copy any file the sandbox
        # user can read straight into the graph's code sidecars.
        self._write_node(_statement("stmt-a"))
        code_dir = os.path.join(self.job_dir, "outbox", "code", "stmt-a")
        os.makedirs(code_dir, exist_ok=True)
        os.symlink("/etc/hosts", os.path.join(code_dir, "analysis.py"))
        self._write_code("stmt-a", "environment.lock", b"numpy==1.26.4\n")

        _documents, code, _rejected = agent.read_outbox(self.job_dir)
        self.assertNotIn("analysis.py", code["stmt-a"])
        self.assertIn("environment.lock", code["stmt-a"])

    def test_a_code_file_with_an_unsafe_relative_path_is_skipped(self):
        self._write_node(_statement("stmt-a"))
        code_dir = os.path.join(self.job_dir, "outbox", "code", "stmt-a")
        os.makedirs(code_dir, exist_ok=True)
        # A name the S3 key rules refuse (leading dot) sits next to a good one.
        with open(os.path.join(code_dir, ".hidden"), "wb") as handle:
            handle.write(b"x")
        self._write_code("stmt-a", "analysis.py", b"y")

        _documents, code, _rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(sorted(code["stmt-a"]), ["analysis.py"])

    def test_an_oversized_code_sidecar_is_capped(self):
        self._write_node(_statement("stmt-a"))
        with patch.object(agent, "MAX_OUTBOX_CODE_BYTES", 8):
            self._write_code("stmt-a", "analysis.py", b"x" * 64)
            _documents, code, _rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(code["stmt-a"], {})

    def test_an_oversized_outbox_is_capped_and_reported(self):
        with patch.object(agent, "MAX_OUTBOX_NODES", 1):
            self._write_node(_entity("ent-a"))
            self._write_node(_entity("ent-b"))
            documents, _code, rejected = agent.read_outbox(self.job_dir)
        self.assertEqual(len(documents), 1)
        self.assertIn("limit is 1", rejected[0]["reason"])


class OutboxValidationTestCase(unittest.TestCase):
    def setUp(self):
        self.existing = {"ent-unit": _entity("ent-unit"), "ent-stim": _entity("ent-stim", "stimulus"),
                         "rel-r": _relation()}

    def test_a_valid_document_is_accepted(self):
        accepted, rejected = agent.validate_outbox([_statement("stmt-a")], self.existing)
        self.assertEqual([d["id"] for d in accepted], ["stmt-a"])
        self.assertEqual(rejected, [])

    def test_a_statement_may_depend_on_another_document_in_the_same_outbox(self):
        documents = [_statement("stmt-b", ["stmt-a"]), _statement("stmt-a")]
        accepted, rejected = agent.validate_outbox(documents, self.existing)
        self.assertEqual(sorted(d["id"] for d in accepted), ["stmt-a", "stmt-b"])
        self.assertEqual(rejected, [])

    def test_a_statement_may_reference_entities_authored_in_the_same_outbox(self):
        documents = [_entity("ent-new"), _relation(), _entity("ent-stim", "stimulus"),
                     {"id": "s", "kind": "statement", "subject": "ent-new", "relation": "rel-r",
                      "object": "ent-stim", "depends_on": []}]
        accepted, _rejected = agent.validate_outbox(documents, {})
        self.assertIn("s", [d["id"] for d in accepted])

    def test_a_dangling_dependency_is_rejected_with_a_reason(self):
        accepted, rejected = agent.validate_outbox([_statement("stmt-a", ["gone"])], self.existing)
        self.assertEqual(accepted, [])
        self.assertIn("gone", rejected[0]["reason"])

    def test_a_document_without_an_id_is_rejected(self):
        _accepted, rejected = agent.validate_outbox([{"kind": "entity"}], {})
        self.assertIn("no id", rejected[0]["reason"])

    def test_a_bad_document_does_not_block_a_good_one(self):
        accepted, rejected = agent.validate_outbox(
            [_statement("stmt-a"), _statement("stmt-bad", ["gone"])], self.existing
        )
        self.assertEqual([d["id"] for d in accepted], ["stmt-a"])
        self.assertEqual(len(rejected), 1)


class AttributionTestCase(unittest.TestCase):
    def test_a_statement_enters_as_proposed_attributed_to_the_agent_job(self):
        doc = agent.attribute(_statement("stmt-a"), "0000-0001", "agent-1")
        self.assertEqual(doc["status"], "proposed")
        self.assertEqual(doc["provenance"]["author"], "0000-0001 via agent job agent-1")

    def test_an_agents_claim_of_verified_status_is_discarded(self):
        doc = _statement("stmt-a")
        doc["status"] = "verified"
        self.assertEqual(agent.attribute(doc, "0000-0001", "agent-1")["status"], "proposed")

    def test_an_agents_provenance_is_replaced(self):
        doc = _statement("stmt-a")
        doc["provenance"] = {"author": "someone-else", "created": "2020-01-01"}
        self.assertNotIn("someone-else", agent.attribute(doc, "0000-0001", "agent-1")["provenance"]["author"])

    def test_entities_carry_no_status(self):
        self.assertNotIn("status", agent.attribute(_entity("ent-a"), "0000-0001", "agent-1"))

    def test_the_creation_is_recorded_in_the_history(self):
        history = agent.attribute(_statement("s"), "0000-0001", "agent-1")["provenance"]["history"]
        self.assertEqual(history[0]["action"], "created")


class JobQueueTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.queue = jobs.JobQueue()

    async def _drain(self, job_id):
        for _ in range(200):
            record = self.queue.get(job_id)
            if record["state"] in ("done", "failed"):
                return record
            await asyncio.sleep(0.01)
        raise AssertionError("job never finished")

    async def test_a_job_runs_and_records_its_result(self):
        record = await self.queue.submit("verify", lambda: {"passed": True}, node_id="stmt-a")
        self.assertEqual(record["state"], "queued")
        finished = await self._drain(record["job_id"])
        self.assertEqual(finished["state"], "done")
        self.assertEqual(finished["result"], {"passed": True})

    async def test_a_failing_job_is_recorded_rather_than_killing_the_worker(self):
        def boom():
            raise RuntimeError("nope")

        record = await self.queue.submit("verify", boom)
        finished = await self._drain(record["job_id"])
        self.assertEqual(finished["state"], "failed")
        self.assertIn("nope", finished["error"])

        follow_up = await self.queue.submit("verify", lambda: {"ok": True})
        self.assertEqual((await self._drain(follow_up["job_id"]))["state"], "done")

    async def test_jobs_run_one_at_a_time(self):
        running = []

        def work(tag):
            running.append(("start", tag))
            running.append(("end", tag))
            return {}

        first = await self.queue.submit("verify", lambda: work("a"))
        second = await self.queue.submit("verify", lambda: work("b"))
        await self._drain(first["job_id"])
        await self._drain(second["job_id"])
        self.assertEqual(running, [("start", "a"), ("end", "a"), ("start", "b"), ("end", "b")])

    async def test_an_unknown_job_is_none(self):
        self.assertIsNone(self.queue.get("nope"))

    async def test_jobs_are_listed_newest_first_and_filtered_by_kind(self):
        await self.queue.submit("verify", lambda: {})
        agent_job = await self.queue.submit("agent", lambda: {})
        listed = self.queue.list_jobs()
        self.assertEqual(listed[0]["job_id"], agent_job["job_id"])
        self.assertEqual(len(self.queue.list_jobs(kind="agent")), 1)

    async def test_old_jobs_are_evicted(self):
        with patch.object(jobs, "MAX_JOBS", 2):
            ids = [(await self.queue.submit("verify", lambda: {}))["job_id"] for _ in range(3)]
        self.assertIsNone(self.queue.get(ids[0]))
        self.assertIsNotNone(self.queue.get(ids[2]))

    async def test_a_record_can_be_updated_in_place(self):
        record = await self.queue.submit("agent", lambda: {})
        self.queue.update(record["job_id"], transcript="hello")
        self.assertEqual(self.queue.get(record["job_id"])["transcript"], "hello")

    async def test_updating_an_unknown_job_is_a_no_op(self):
        self.queue.update("nope", transcript="x")

    async def test_reset_clears_every_job(self):
        record = await self.queue.submit("verify", lambda: {})
        self.queue.reset()
        self.assertIsNone(self.queue.get(record["job_id"]))

    async def test_job_counts_tally_by_state(self):
        record = await self.queue.submit("verify", lambda: {})
        await self._drain(record["job_id"])
        with patch.object(jobs, "queue", self.queue):
            self.assertEqual(jobs.job_counts().get("done"), 1)


if __name__ == "__main__":
    unittest.main()
