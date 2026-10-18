"""Share only in-flight recognition work for the same owner and uploaded image.

No completed result is cached. Entries and GPU admission remain bounded, and
one disconnected caller cannot cancel work still needed by another caller.
"""
import asyncio
from dataclasses import dataclass


class RecognitionBusy(Exception):
    pass


@dataclass
class _Job:
    task: asyncio.Task
    waiters: int = 0


class RecognitionJobs:
    def __init__(self, capacity):
        self.capacity = max(1, capacity)
        self._jobs = {}

    def _finished(self, key, job):
        if self._jobs.get(key) is job:
            del self._jobs[key]
        # Retrieve failures even if every waiting request disconnected.
        if not job.task.cancelled():
            job.task.exception()

    async def run(self, key, factory):
        job = self._jobs.get(key)
        if job is not None and job.task.done():
            self._finished(key, job)
            job = None
        shared = job is not None
        if job is None:
            if len(self._jobs) >= self.capacity:
                raise RecognitionBusy()
            job = _Job(asyncio.create_task(factory()))
            self._jobs[key] = job
            job.task.add_done_callback(lambda _: self._finished(key, job))
        elif job.task.cancelling():
            # The last waiter left; let upstream cleanup finish before retry.
            raise RecognitionBusy()
        job.waiters += 1
        try:
            return await asyncio.shield(job.task), shared
        finally:
            job.waiters -= 1
            if not job.waiters and not job.task.done():
                job.task.cancel()

    async def close(self):
        jobs = list(self._jobs.values())
        for job in jobs:
            if not job.task.cancelling():
                job.task.cancel()
        await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)
