"""In-process serial job queue for verification runs and agent jobs.

Both kinds of work execute untrusted code under a CPU and memory budget, so
they run **one at a time**: a single worker task pulls from an ``asyncio``
queue and awaits each job in a thread. The portal is a single uvicorn process
today - the same constraint the in-memory chat rate limiter already accepts -
so an in-process queue is the right size for the demo. Moving the work to a
separate ECS task later changes this module and nothing else.

Job records are kept in memory, newest ``MAX_JOBS`` retained, and are what
``GET /verification/agent/jobs/{job_id}`` polls.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from typing import Callable, Dict, Optional

from .graph import now_iso

logger = logging.getLogger(__name__)

MAX_JOBS = 200


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

    def list_jobs(self, kind: Optional[str] = None) -> list:
        """Return every retained job record, newest first."""
        records = [dict(r) for r in self._jobs.values()]
        if kind:
            records = [r for r in records if r.get("kind") == kind]
        records.reverse()
        return records

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
        while len(self._jobs) > MAX_JOBS:
            self._jobs.popitem(last=False)

        async with self._lock:
            if self._queue is None:
                self._queue = asyncio.Queue()
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(self._run_worker())
        await self._queue.put((job_id, work))
        return dict(record)

    async def _run_worker(self) -> None:
        """Drain the queue one job at a time until it is empty."""
        assert self._queue is not None
        while True:
            try:
                job_id, work = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
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


def job_counts() -> Dict[str, int]:
    """Return how many retained jobs sit in each lifecycle state."""
    counts: Dict[str, int] = {}
    for record in queue.list_jobs():
        state = record.get("state", "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts
