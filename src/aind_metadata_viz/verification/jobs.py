"""In-process serial job queue for verification runs.

A verification run executes untrusted node code under a CPU and memory budget,
so runs happen **one at a time**: a single worker task pulls from an
``asyncio`` queue and awaits each job in a thread. The portal is a single
uvicorn process today - the same constraint the in-memory chat rate limiter
already accepts - so an in-process queue is the right size for this. Moving
the work to a separate ECS task later changes this module and nothing else.

Job records are kept in memory, newest ``MAX_JOBS`` retained, and are what
``GET /verification/jobs/{job_id}`` polls.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from typing import Callable, List, Optional

from .graph import now_iso

logger = logging.getLogger(__name__)

MAX_JOBS = 200

_TERMINAL_STATES = {"done", "failed"}


class JobQueue:
    """A serial queue of background jobs with in-memory status records."""

    def __init__(self):
        """Create an empty queue; the worker starts on the first submission."""
        self._jobs: "OrderedDict[str, dict]" = OrderedDict()
        self._queue: Optional[asyncio.Queue] = None
        self._worker: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def get(self, job_id: str) -> Optional[dict]:
        """Return a copy of a job's record, or None when it is unknown."""
        record = self._jobs.get(job_id)
        return dict(record) if record else None

    def list(self, state: Optional[str] = None, limit: int = MAX_JOBS) -> List[dict]:
        """Return job records newest-first, optionally filtered by state.

        A batch verify can enqueue thousands of jobs well past ``MAX_JOBS`` at
        once (see ``_evict_oldest_terminal``); this still only ever returns at
        most ``limit`` of them, so a dashboard polling this never has to page
        through a backlog to see what is currently running.
        """
        records = [dict(record) for record in reversed(self._jobs.values())]
        if state is not None:
            records = [record for record in records if record["state"] == state]
        return records[: max(0, limit)]

    def pending(self, node_id: str, axis: str) -> bool:
        """Return True if a queued or running job already targets this node+axis.

        Used to make re-submitting a batch verify idempotent: a node already
        in flight is skipped rather than queued a second time.
        """
        return any(
            record["node_id"] == node_id and record.get("axis") == axis and record["state"] in ("queued", "running")
            for record in self._jobs.values()
            if record.get("kind") == "verify"
        )

    def _evict_oldest_terminal(self) -> bool:
        """Drop the oldest done/failed record, if any exists.

        A job that is still ``queued`` or ``running`` is never evicted just
        for being old - the whole point of ``MAX_JOBS`` is to bound *history*
        retention, not to drop work that has not run yet. A mass verify can
        submit far more than ``MAX_JOBS`` jobs before the single worker drains
        them; if the oldest were evicted unconditionally, ``_run_one`` would
        find no record for it, assume it had been evicted mid-flight, and
        silently skip running it at all (see its own early-return for exactly
        that case). So the backlog is allowed to temporarily exceed MAX_JOBS
        rather than lose queued work.
        """
        for job_id, record in self._jobs.items():
            if record["state"] in _TERMINAL_STATES:
                del self._jobs[job_id]
                return True
        return False

    async def submit(
        self, kind: str, work: Callable[[], dict], job_id: Optional[str] = None, **fields
    ) -> dict:
        """Queue *work* and return the job's initial record.

        *work* is a blocking callable run in a worker thread; whatever dict it
        returns becomes the job's ``result``. Pass *job_id* when the caller has
        to know the id up front - an agent job wires it into the work so the
        cancel and steer endpoints can find the running session.
        """
        job_id = job_id or f"{kind}-{uuid.uuid4().hex[:12]}"
        record = {
            "job_id": job_id,
            "kind": kind,
            "state": "queued",
            "created": now_iso(),
            "finished": None,
            "error": None,
            "result": None,
            **fields,
        }
        self._jobs[job_id] = record
        while len(self._jobs) > MAX_JOBS and self._evict_oldest_terminal():
            pass

        async with self._lock:
            if self._queue is None:
                self._queue = asyncio.Queue()
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(self._run_worker())
        await self._queue.put((job_id, work))
        return dict(record)

    async def _run_worker(self) -> None:
        """Drain the queue one job at a time until it is empty.

        Retiring is done under the lock, and only after re-checking that the
        queue really is empty. Without that there is a window where a
        ``submit`` sees a worker that has decided to stop but has not finished
        stopping, declines to start a replacement, and leaves its job sitting
        in ``queued`` for ever.
        """
        assert self._queue is not None
        while True:
            try:
                job_id, work = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                async with self._lock:
                    if self._queue.empty():
                        self._worker = None
                        return
                continue
            await self._run_one(job_id, work)

    async def _run_one(self, job_id: str, work: Callable[[], dict]) -> None:
        """Run one job, recording its outcome on the job record."""
        record = self._jobs.get(job_id)
        if record is None:  # pragma: no cover - only if evicted mid-flight
            return
        record["state"] = "running"
        try:
            record["result"] = await asyncio.to_thread(work)
            record["state"] = "done"
        except Exception as exc:  # noqa: BLE001 - a failed job must not kill the worker
            logger.exception("verification job %s failed", job_id)
            record["state"] = "failed"
            record["error"] = str(exc)
        finally:
            record["finished"] = now_iso()

    def update(self, job_id: str, **fields) -> None:
        """Merge *fields* into a job's record, if it still exists."""
        record = self._jobs.get(job_id)
        if record is not None:
            record.update(fields)

    def reset(self) -> None:
        """Drop every retained job. Used in tests."""
        self._jobs.clear()


#: The process-wide queue. Verification runs and agent jobs share it, so heavy
#: work never overlaps.
queue = JobQueue()
