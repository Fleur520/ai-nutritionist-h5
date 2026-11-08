import asyncio
import json
import time
import uuid

import pytest
from fastapi import HTTPException

from app.chat_jobs import ChatJobs


def event(kind, data):
    return f'event: {kind}\ndata: {json.dumps(data)}\n\n'


def test_incremental_cursor_ownership_capacity_and_cancellation():
    async def run():
        jobs = ChatJobs(capacity=1)
        gate = asyncio.Event()
        closed = []
        async def source():
            try:
                yield event('delta', {'content': '第一段'})
                await gate.wait()
                yield event('delta', {'content': '第二段'})
                yield event('done', {})
            finally:
                closed.append(True)
        key = jobs.start('alice', 'thread', source)
        await asyncio.sleep(0.01)
        first = jobs.read(key, 'alice', 0)
        assert first['state'] == 'running' and first['cursor'] == 1
        assert jobs.read(key, 'alice', 1)['frames'] == []
        for owner, thread, status in [('alice', 'thread', 409), ('bob', 'other', 429)]:
            with pytest.raises(HTTPException) as error:
                jobs.start(owner, thread, source)
            assert error.value.status_code == status
        for action in [lambda: jobs.read(key, 'bob', 0), lambda: jobs.read('unknown', 'alice', 0)]:
            with pytest.raises(HTTPException) as error:
                action()
            assert error.value.status_code == 404
        with pytest.raises(HTTPException):
            await jobs.stop(key, 'bob')
        with pytest.raises(HTTPException):
            jobs.read(key, 'alice', 99)
        gate.set()
        await jobs.jobs[key].task
        update = jobs.read(key, 'alice', first['cursor'])
        assert update['state'] == 'complete' and len(update['frames']) == 2
        assert closed == [True]
        gate.clear()
        second = jobs.start('alice', 'thread', source)
        await asyncio.sleep(0.01)
        assert (await jobs.stop(second, 'alice'))['state'] == 'stopped'
        assert len(closed) == 2
        await jobs.close()
    asyncio.run(run())


def test_idle_timeout_failure_and_expired_results_are_bounded():
    async def run():
        jobs = ChatJobs(idle_timeout=0.01)
        async def slow():
            yield event('delta', {'content': 'partial'})
            await asyncio.sleep(10)
        key = jobs.start('alice', 'slow', slow)
        await asyncio.sleep(0.05)
        assert jobs.read(key, 'alice', 0)['state'] == 'stopped'
        jobs.jobs[key].finished -= 121
        with pytest.raises(HTTPException):
            jobs.read(key, 'alice', 0)
        for payload in ['x' * 128001, '汉' * 50000]:
            async def oversized():
                yield payload
            key = jobs.start('alice', 'large', oversized)
            await jobs.jobs[key].task
            result = jobs.read(key, 'alice', 0)
            assert result['state'] == 'failed' and len(result['frames']) == 1
            assert 'event: error' in result['frames'][0]
        await jobs.close()
    asyncio.run(run())


def test_job_api_delivers_before_completion_and_stops_without_saving_partial(monkeypatch):
    from fastapi.testclient import TestClient
    from test_api import app
    from app import main

    calls = []
    async def chunks(message, history, profile):
        calls.append(message)
        yield '第一段'
        await asyncio.sleep(20 if message == 'stop' else 0.2)
        yield '第二段'
    monkeypatch.setattr(main, 'chat_chunks', chunks)
    with TestClient(app) as client:
        email = 'jobs-' + uuid.uuid4().hex + '@example.com'
        credentials = {'email': email, 'password': 'test-password-123'}
        assert client.post('/api/auth/register', json=credentials).status_code == 201
        start = client.post('/api/chat/jobs', json={'message': 'test', 'thread_id': 'job-test'})
        assert start.status_code == 202 and 'no-store' in start.headers['cache-control']
        key = start.json()['id']
        partial = None
        for _ in range(100):
            update = client.get('/api/chat/jobs/' + key).json()
            if any('event: delta' in frame for frame in update['frames']):
                partial = update
                break
            time.sleep(0.01)
        assert partial and partial['state'] == 'running'
        for _ in range(100):
            update = client.get('/api/chat/jobs/' + key, params={'after': partial['cursor']}).json()
            if update['state'] == 'complete':
                break
            time.sleep(0.01)
        assert update['state'] == 'complete' and calls == ['test']
        history = client.get('/api/chat/history?thread_id=job-test').json()
        assert [row['content'] for row in history if row['role'] == 'assistant'] == ['第一段第二段']
        bob = {'email': 'other-' + uuid.uuid4().hex + '@example.com', 'password': 'test-password-123'}
        assert client.post('/api/auth/register', json=bob).status_code == 201
        assert client.get('/api/chat/jobs/' + key).status_code == 404
        assert client.delete('/api/chat/jobs/' + key).status_code == 404
        assert client.post('/api/auth/login', json=credentials).status_code == 200
        second = client.post('/api/chat/jobs', json={'message': 'stop', 'thread_id': 'job-stop'}).json()['id']
        for _ in range(100):
            if len(client.get('/api/chat/jobs/' + second).json()['frames']) >= 2:
                break
            time.sleep(0.01)
        assert client.delete('/api/chat/jobs/' + second).json()['state'] == 'stopped'
        assert not any(row['role'] == 'assistant' for row in client.get('/api/chat/history?thread_id=job-stop').json())
