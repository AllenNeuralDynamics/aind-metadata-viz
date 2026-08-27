"""Tests for the in-process serial job queue behind verification runs."""

import asyncio
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

    def test_old_records_are_evicted_once_the_cap_is_passed(self):
        async def scenario():
            queue = jobs.JobQueue()
            first = None
            for index in range(jobs.MAX_JOBS + 3):
                record = await queue.submit("verify", lambda: {}, job_id=f"verify-{index}")
                if index == 0:
                    first = record["job_id"]
            await _drain(400)
            return queue, first

        queue, first = asyncio.run(scenario())
        self.assertIsNone(queue.get(first))
        self.assertIsNotNone(queue.get(f"verify-{jobs.MAX_JOBS + 2}"))

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

    def test_the_worker_is_cleared_once_the_queue_drains(self):
        async def scenario():
            queue = jobs.JobQueue()
            await queue.submit("verify", lambda: {})
            await _drain(80)
            return queue

        self.assertIsNone(asyncio.run(scenario())._worker)


if __name__ == "__main__":
    unittest.main()
