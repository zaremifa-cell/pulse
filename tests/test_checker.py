import asyncio
import time
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pulse import checker
from pulse.models import Check, Incident, Monitor, State

from .conftest import public_resolver


def client_for(responses):
    """A fake internet: maps host -> status code, 'hang' or an exception."""

    async def handler(request):
        outcome = responses[request.url.host]
        if outcome == "hang":
            await asyncio.sleep(5)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def add(sessions, name, **kw):
    async with sessions() as s, s.begin():
        monitor = Monitor(name=name, url=f"https://{name}.test/", **kw)
        s.add(monitor)
    return monitor.id


async def run(sessions, client, at=None):
    return await checker.run_due(sessions, client, resolve=public_resolver, at=at)


async def state(sessions, monitor_id):
    async with sessions() as s:
        monitor = await s.get(Monitor, monitor_id)
        incidents = (await s.scalars(select(Incident).where(Incident.monitor_id == monitor_id))).all()
        return monitor, incidents


async def run_rounds(sessions, client, n):
    at = checker.now()
    for i in range(n):
        await run(sessions, client, at=at + timedelta(minutes=i + 1))


async def test_a_healthy_site_is_up(sessions):
    mid = await add(sessions, "ok")
    async with client_for({"ok.test": 200}) as client:
        assert await run(sessions, client) == 1
    monitor, incidents = await state(sessions, mid)
    assert monitor.state == State.UP and incidents == []


async def test_one_failure_is_degraded_not_down(sessions):
    mid = await add(sessions, "flaky")
    async with client_for({"flaky.test": 503}) as client:
        await run(sessions, client)
    monitor, incidents = await state(sessions, mid)
    assert monitor.state == State.DEGRADED and monitor.consecutive_failures == 1 and incidents == []


async def test_three_failures_in_a_row_open_exactly_one_incident(sessions):
    mid = await add(sessions, "dead")
    async with client_for({"dead.test": 500}) as client:
        await run_rounds(sessions, client, 5)
    monitor, incidents = await state(sessions, mid)
    assert monitor.state == State.DOWN
    assert len(incidents) == 1
    assert incidents[0].cause == "HTTP 500" and incidents[0].failed_checks == 5 and incidents[0].resolved_at is None


async def test_recovery_resolves_the_incident(sessions):
    mid = await add(sessions, "back")
    responses = {"back.test": 500}
    async with client_for(responses) as client:
        await run_rounds(sessions, client, 3)
        responses["back.test"] = 200
        await run(sessions, client, at=checker.now() + timedelta(minutes=10))
    monitor, incidents = await state(sessions, mid)
    assert monitor.state == State.UP and monitor.consecutive_failures == 0
    assert incidents[0].resolved_at is not None


async def test_a_success_between_failures_resets_the_count(sessions):
    mid = await add(sessions, "wobbly")
    responses = {"wobbly.test": 500}
    at = checker.now()
    async with client_for(responses) as client:
        for i, code in enumerate([500, 500, 200, 500, 500]):
            responses["wobbly.test"] = code
            await run(sessions, client, at=at + timedelta(minutes=i + 1))
    monitor, incidents = await state(sessions, mid)
    assert monitor.state == State.DEGRADED and incidents == []


async def test_redirects_count_as_up_and_errors_as_down(sessions):
    up = await add(sessions, "moved")
    down = await add(sessions, "refused")
    async with client_for({"moved.test": 301, "refused.test": httpx.ConnectError("Connection refused")}) as client:
        await run(sessions, client)
    assert (await state(sessions, up))[0].state == State.UP
    async with sessions() as s:
        check = await s.scalar(select(Check).where(Check.monitor_id == down))
    assert not check.ok and "ConnectError" in check.error


async def test_a_hanging_site_times_out_without_delaying_the_others(sessions):
    slow = await add(sessions, "slow", timeout_seconds=0.3)
    for i in range(5):
        await add(sessions, f"fast{i}")
    responses = {"slow.test": "hang", **{f"fast{i}.test": 200 for i in range(5)}}
    async with client_for(responses) as client:
        started = time.perf_counter()
        assert await run(sessions, client) == 6
        elapsed = time.perf_counter() - started
    assert elapsed < 1.5  # checked together, not one after another
    async with sessions() as s:
        check = await s.scalar(select(Check).where(Check.monitor_id == slow))
    assert check.error == "No answer within 0.3s"


async def test_two_checkers_at_once_never_check_a_monitor_twice(sessions):
    for i in range(10):
        await add(sessions, f"site{i}")

    async def handler(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        counts = await asyncio.gather(run(sessions, client), run(sessions, client))
    assert sum(counts) == 10
    async with sessions() as s:
        assert await s.scalar(select(func.count()).select_from(Check)) == 10


async def test_monitors_that_are_not_due_are_skipped(sessions):
    await add(sessions, "later", next_check_at=checker.now() + timedelta(minutes=5))
    async with client_for({}) as client:
        assert await run(sessions, client) == 0


async def test_a_monitor_pointing_inside_the_network_fails_safely(sessions):
    mid = await add(sessions, "internal")

    async def private(host):
        return ["10.0.0.1"]

    async with client_for({}) as client:
        await checker.run_due(sessions, client, resolve=private)
    async with sessions() as s:
        check = await s.scalar(select(Check).where(Check.monitor_id == mid))
    assert not check.ok and "private" in check.error


async def test_the_database_refuses_a_second_open_incident(sessions):
    mid = await add(sessions, "x")
    with pytest.raises(IntegrityError):
        async with sessions() as s, s.begin():
            s.add_all(
                [
                    Incident(monitor_id=mid, started_at=checker.now(), cause="a", failed_checks=3),
                    Incident(monitor_id=mid, started_at=checker.now(), cause="b", failed_checks=3),
                ]
            )
