import asyncio

import pytest

from app.recognition_jobs import RecognitionBusy, RecognitionJobs


def test_duplicate_calls_share_work_but_completed_results_are_not_cached():
    async def scenario():
        jobs = RecognitionJobs(2)
        release = asyncio.Event()
        calls = []
        async def work():
            calls.append(True)
            await release.wait()
            return {'food': 'rice'}
        requests = [asyncio.create_task(jobs.run(('owner', 'image'), work)) for _ in range(10)]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*requests)
        assert len(calls) == 1
        assert sum(shared for _, shared in results) == 9
        assert all(result == {'food': 'rice'} for result, _ in results)
        assert not jobs._jobs
        assert await jobs.run(('owner', 'image'), work) == ({'food': 'rice'}, False)
        assert len(calls) == 2
    asyncio.run(scenario())


def test_image_and_owner_are_both_part_of_identity_and_capacity_is_bounded():
    async def scenario():
        jobs = RecognitionJobs(3)
        release = asyncio.Event()
        entered = []
        async def work():
            entered.append(True)
            await release.wait()
        keys = [('a', 'image'), ('b', 'image'), ('a', 'other')]
        requests = [asyncio.create_task(jobs.run(key, work)) for key in keys]
        await asyncio.sleep(0)
        with pytest.raises(RecognitionBusy):
            await jobs.run(('c', 'image'), work)
        follower = asyncio.create_task(jobs.run(keys[0], work))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*requests, follower)
        assert len(entered) == 3
        assert [shared for _, shared in results] == [False, False, False, True]
        assert not jobs._jobs
    asyncio.run(scenario())


def test_one_cancelled_waiter_does_not_cancel_other_waiters():
    async def scenario():
        jobs = RecognitionJobs(1)
        release, started = asyncio.Event(), asyncio.Event()
        cancelled = []
        async def work():
            started.set()
            try:
                await release.wait()
                return 'ok'
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
        first = asyncio.create_task(jobs.run(('owner', 'image'), work))
        await started.wait()
        second = asyncio.create_task(jobs.run(('owner', 'image'), work))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        assert not cancelled
        release.set()
        assert await second == ('ok', True)
        assert not cancelled and not jobs._jobs
    asyncio.run(scenario())


def test_last_waiter_cancels_upstream_and_busy_entry_survives_until_cleanup():
    async def scenario():
        jobs = RecognitionJobs(1)
        started, stopping, stop_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def work():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopping.set()
                await stop_done.wait()
        request = asyncio.create_task(jobs.run(('owner', 'image'), work))
        await started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError): await request
        await stopping.wait()
        with pytest.raises(RecognitionBusy):
            await jobs.run(('owner', 'image'), work)
        assert len(jobs._jobs) == 1
        stop_done.set()
        await asyncio.gather(*(job.task for job in list(jobs._jobs.values())), return_exceptions=True)
        assert not jobs._jobs
        async def retry(): return 'retry'
        assert await jobs.run(('owner', 'image'), retry) == ('retry', False)
    asyncio.run(scenario())


def test_failures_reach_all_waiters_and_retry_runs_again():
    async def scenario():
        jobs = RecognitionJobs(1)
        release = asyncio.Event()
        async def fail():
            await release.wait()
            raise ValueError('upstream failed')
        requests = [asyncio.create_task(jobs.run(('owner', 'image'), fail)) for _ in range(3)]
        await asyncio.sleep(0)
        release.set()
        failures = await asyncio.gather(*requests, return_exceptions=True)
        assert all(isinstance(error, ValueError) for error in failures)
        assert not jobs._jobs
        async def retry(): return 'fresh'
        assert await jobs.run(('owner', 'image'), retry) == ('fresh', False)
    asyncio.run(scenario())


def test_shutdown_waits_for_active_tasks_to_stop():
    async def scenario():
        jobs = RecognitionJobs(1)
        started = asyncio.Event()
        stopped = []
        async def work():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(True)
        request = asyncio.create_task(jobs.run(('owner', 'image'), work))
        await started.wait()
        await jobs.close()
        with pytest.raises(asyncio.CancelledError): await request
        assert stopped == [True] and not jobs._jobs
    asyncio.run(scenario())
