"""Tests for the in-process serial job queue behind verification runs."""

import asyncio
import threading
import unittest

from aind_metadata_viz.verification import jobs


async def _drain(loops=80):
    """Yield to the event loop enough times for the worker to finish."""
    for _ in range(loops):
        await asyncio.sleep(0)


class JobQueueTestCase(unittest.TestCase):
    def test_a_submitted_job_runs_and_records_its_result(self):
        async def scenario():
            queue = jobs.JobQueue()
            record = await queue.submit("verify", lambda: {"passed": True})
            await _drain()
            return record, queue.get(record["job_id"])

        initial, final = asyncio.run(scenario())
        self.assertEqual(initial["state"], "queued")
        self.assertEqual(final["state"], "done")
        self.assertEqual(final["result"], {"passed": True})
        self.assertIsNotNone(final["finished"])

    def test_extra_fields_are_kept_on_the_record(self):
        async def scenario():
            queue = jobs.JobQueue()
            record = await queue.submit(
                "verify", lambda: {}, node_id="stmt-a", axis="reproducible"
            )
            return queue.get(record["job_id"])

        record = asyncio.run(scenario())
        self.assertEqual(record["node_id"], "stmt-a")
        self.assertEqual(record["axis"], "reproducible")

    def test_an_explicit_job_id_is_honoured(self):
        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: {}, job_id="verify-fixed")
            return queue.get("verify-fixed")

        self.assertIsNotNone(asyncio.run(scenario()))

    def test_a_failing_job_is_recorded_without_killing_the_worker(self):
        async def scenario():
            queue = jobs.JobQueue()
            boom = await queue.submit("verify", lambda: (_ for _ in ()).throw(RuntimeError("nope")))
            await _drain()
            fine = await queue.submit("verify", lambda: {"ok": True})
            await _drain()
            return queue.get(boom["job_id"]), queue.get(fine["job_id"])

        failed, succeeded = asyncio.run(scenario())
        self.assertEqual(failed["state"], "failed")
        self.assertIn("nope", failed["error"])
        self.assertEqual(succeeded["state"], "done")

    def test_jobs_run_one_at_a_time(self):
        order = []

        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: order.append("start-a") or order.append("end-a"))
            await queue.submit("verify", lambda: order.append("start-b") or order.append("end-b"))
            await _drain(160)

        asyncio.run(scenario())
        self.assertEqual(order, ["start-a", "end-a", "start-b", "end-b"])

    def test_an_unknown_job_id_reads_as_none(self):
        self.assertIsNone(jobs.JobQueue().get("nope"))

    def test_update_merges_fields_into_a_record(self):
        async def scenario():
            queue = jobs.JobQueue()
            record = await queue.submit("verify", lambda: {})
            queue.update(record["job_id"], note="touched")
            return queue.get(record["job_id"])

        self.assertEqual(asyncio.run(scenario())["note"], "touched")

    def test_updating_an_unknown_job_is_a_no_op(self):
        jobs.JobQueue().update("nope", note="x")  # must not raise

    def test_old_finished_records_are_evicted_once_the_cap_is_passed(self):
        async def scenario():
            queue = jobs.JobQueue()
            first = None
            for index in range(jobs.MAX_JOBS + 2):
                record = await queue.submit("verify", lambda: {}, job_id=f"verify-{index}")
                if index == 0:
                    first = record["job_id"]
            await _drain(400)
            # Eviction is opportunistic on submission, not on completion: one
            # more submit now that everything above has finished is what
            # actually trims the stale backlog down to MAX_JOBS.
            await queue.submit("verify", lambda: {}, job_id="verify-trigger")
            await _drain(40)
            return queue, first

        queue, first = asyncio.run(scenario())
        self.assertIsNone(queue.get(first))
        self.assertIsNotNone(queue.get(f"verify-{jobs.MAX_JOBS + 1}"))
        self.assertIsNotNone(queue.get("verify-trigger"))

    def test_a_burst_past_the_cap_is_never_silently_dropped(self):
        """Regression test: a mass verify can submit far more than MAX_JOBS
        jobs before the single worker drains even one of them. The old
        eviction rule (drop the oldest record regardless of its state) would
        delete the bookkeeping for still-queued jobs; _run_one then finds no
        record, assumes it was evicted mid-flight, and skips running it -
        silently. Every submitted job must still actually run."""
        gate = threading.Event()
        ran = []

        def blocking_first():
            gate.wait(timeout=5)
            ran.append(0)
            return {}

        def quick(index):
            return lambda: ran.append(index) or {}

        total = jobs.MAX_JOBS + 50

        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", blocking_first, job_id="verify-0")
            # Job 0 is still "running" (the gate is not set yet), so nothing
            # submitted below is eligible for eviction - the backlog must be
            # allowed to grow past MAX_JOBS rather than drop any of them.
            for index in range(1, total):
                await queue.submit("verify", quick(index), job_id=f"verify-{index}")
            backlog_at_burst = len(queue._jobs)
            gate.set()
            # 250 real thread-pool dispatches take actual OS scheduling time;
            # a bare sleep(0) drain isn't reliably enough of them.
            for _ in range(500):
                if len(ran) >= total:
                    break
                await asyncio.sleep(0.01)
            return queue, backlog_at_burst

        queue, backlog_at_burst = asyncio.run(scenario())
        self.assertGreater(backlog_at_burst, jobs.MAX_JOBS)
        self.assertEqual(sorted(ran), list(range(total)))
        for index in range(total):
            self.assertEqual(queue.get(f"verify-{index}")["state"], "done")

    def test_reset_clears_every_record(self):
        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: {}, job_id="verify-1")
            queue.reset()
            return queue.get("verify-1")

        self.assertIsNone(asyncio.run(scenario()))

    def test_a_job_submitted_as_the_worker_retires_still_runs(self):
        # The worker retires under the lock after re-checking the queue.
        # Without that, a job arriving in that window is stranded for ever.
        async def scenario():
            queue = jobs.JobQueue()
            ran = []
            await queue.submit("verify", lambda: ran.append("first") or {})
            await _drain(40)
            await queue.submit("verify", lambda: ran.append("second") or {})
            await _drain(120)
            return ran

        self.assertEqual(asyncio.run(scenario()), ["first", "second"])

    def test_the_worker_does_not_retire_while_the_queue_looks_busy(self):
        # Exercises the re-check: the queue reported empty to get_nowait but not
        # to the guarded empty() check, so the worker must loop rather than
        # retire and risk stranding whatever arrived.
        class _StubQueue:
            """A queue that is empty to get_nowait but busy on its first check."""

            def __init__(self):
                """Start with no recorded checks."""
                self.checks = []

            def get_nowait(self):
                """Always report empty."""
                raise asyncio.QueueEmpty

            def empty(self):
                """Look busy once, then settle."""
                self.checks.append(1)
                return len(self.checks) > 1

        async def scenario():
            queue = jobs.JobQueue()
            stub = _StubQueue()
            queue._queue = stub
            await queue._run_worker()
            return stub, queue

        stub, queue = asyncio.run(scenario())
        self.assertEqual(len(stub.checks), 2)
        self.assertIsNone(queue._worker)

    def test_list_returns_newest_first(self):
        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: {}, job_id="verify-a", node_id="a", axis="reproducible")
            await queue.submit("verify", lambda: {}, job_id="verify-b", node_id="b", axis="reproducible")
            await _drain(40)
            return queue

        queue = asyncio.run(scenario())
        self.assertEqual([r["job_id"] for r in queue.list()], ["verify-b", "verify-a"])

    def test_list_filters_by_state(self):
        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: (_ for _ in ()).throw(RuntimeError("x")), job_id="verify-fail")
            await queue.submit("verify", lambda: {}, job_id="verify-ok")
            await _drain(40)
            return queue

        queue = asyncio.run(scenario())
        self.assertEqual([r["job_id"] for r in queue.list(state="failed")], ["verify-fail"])
        self.assertEqual([r["job_id"] for r in queue.list(state="done")], ["verify-ok"])

    def test_list_respects_limit(self):
        async def scenario():
            queue = jobs.JobQueue()
            for index in range(5):
                await queue.submit("verify", lambda: {}, job_id=f"verify-{index}")
            await _drain(40)
            return queue

        queue = asyncio.run(scenario())
        self.assertEqual(len(queue.list(limit=2)), 2)

    def test_pending_is_true_for_a_queued_or_running_job(self):
        gate = threading.Event()

        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit(
                "verify", lambda: gate.wait(timeout=5) or {}, node_id="stmt-a", axis="reproducible"
            )
            pending = queue.pending("stmt-a", "reproducible")
            gate.set()
            await _drain(40)
            return queue, pending

        queue, pending = asyncio.run(scenario())
        self.assertTrue(pending)
        self.assertFalse(queue.pending("stmt-a", "reproducible"))

    def test_pending_is_false_for_a_different_node_or_axis(self):
        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: {}, node_id="stmt-a", axis="reproducible")
            return queue

        queue = asyncio.run(scenario())
        self.assertFalse(queue.pending("stmt-b", "reproducible"))
        self.assertFalse(queue.pending("stmt-a", "replicable"))

    def test_the_worker_is_cleared_once_the_queue_drains(self):
        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: {})
            await _drain(80)
            return queue

        self.assertIsNone(asyncio.run(scenario())._worker)


if __name__ == "__main__":
    unittest.main()
