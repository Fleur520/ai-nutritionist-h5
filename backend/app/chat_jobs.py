"""Bounded owner-scoped incremental delivery for proxies that buffer SSE.

This transport needs a single API worker or sticky routing/shared job storage.
"""
import asyncio
from dataclasses import dataclass, field
import json
import time
import uuid

from fastapi import HTTPException


@dataclass
class ChatJob:
    owner: str
    thread: str
    touched: float = field(default_factory=time.monotonic)
    finished: float | None = None
    state: str = 'running'
    frames: list[str] = field(default_factory=list)
    size: int = 0
    task: asyncio.Task | None = None


class ChatJobs:
    def __init__(self, capacity=10, retention=120, idle_timeout=20, max_duration=180):
        self.capacity = max(1, capacity)
        self.retention = retention
        self.idle_timeout = idle_timeout
        self.max_duration = max_duration
        self.jobs: dict[str, ChatJob] = {}

    def _prune(self):
        now = time.monotonic()
        for key, job in list(self.jobs.items()):
            if job.finished is not None and now - job.finished > self.retention:
                del self.jobs[key]
        completed = sorted(((key, job) for key, job in self.jobs.items() if job.finished is not None), key=lambda entry: entry[1].finished)
        for key, _ in completed[:max(0, len(self.jobs) - 127)]:
            del self.jobs[key]

    def start(self, owner, thread, source):
        self._prune()
        running = [job for job in self.jobs.values() if job.state == 'running']
        if any(job.owner == owner and job.thread == thread for job in running):
            raise HTTPException(409, '这个对话仍在生成回复，请稍候或先停止回答')
        if len(running) >= self.capacity:
            raise HTTPException(429, 'AI 请求繁忙，请稍后再试')
        key = str(uuid.uuid4())
        job = ChatJob(owner, thread)
        self.jobs[key] = job
        job.task = asyncio.create_task(self._run(job, source))
        return key

    async def _watch(self, job):
        while job.state == 'running':
            await asyncio.sleep(min(2, self.idle_timeout))
            if time.monotonic() - job.touched > self.idle_timeout:
                job.task.cancel()
                return

    async def _run(self, job, source):
        watcher = asyncio.create_task(self._watch(job))
        iterator = source()
        try:
            async def consume():
                async for frame in iterator:
                    job.size += len(frame.encode('utf-8'))
                    if job.size > 128_000 or len(job.frames) >= 8192:
                        raise ValueError('chat output exceeds delivery limit')
                    job.frames.append(frame)
                    if frame.startswith('event: done\n'):
                        job.state = 'complete'
                    elif frame.startswith('event: error\n'):
                        job.state = 'failed'
                if job.state == 'running':
                    raise ValueError('chat did not complete')
            await asyncio.wait_for(consume(), timeout=self.max_duration)
        except asyncio.CancelledError:
            job.state = 'stopped'
        except Exception:
            job.state = 'failed'
            job.frames.append('event: error\ndata: ' + json.dumps({'message': '咨询服务暂时不可用，请稍后再试'}, ensure_ascii=False) + '\n\n')
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            await iterator.aclose()
            job.finished = time.monotonic()

    def _owned(self, key, owner):
        self._prune()
        job = self.jobs.get(key)
        if job is None or job.owner != owner:
            raise HTTPException(404, '回复不存在或已过期，请重新提问')
        return job

    def read(self, key, owner, after):
        job = self._owned(key, owner)
        if after < 0 or after > len(job.frames):
            raise HTTPException(422, '回复读取位置无效')
        job.touched = time.monotonic()
        return {'frames': job.frames[after:], 'cursor': len(job.frames), 'state': job.state}

    async def stop(self, key, owner):
        job = self._owned(key, owner)
        if job.state == 'running':
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            job.state = 'stopped'
            job.finished = time.monotonic()
        return {'state': job.state}

    async def close(self):
        tasks = [job.task for job in self.jobs.values() if job.task is not None and not job.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
