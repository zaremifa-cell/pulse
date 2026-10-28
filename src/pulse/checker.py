"""Runs the checks and turns raw results into states and incidents.

- Every due monitor is checked concurrently, each with its own timeout, so one hanging site
  can't delay the others.
- A site is DOWN only after `failure_threshold` failures in a row; a single slow answer makes
  it DEGRADED, not down. That avoids false alarms.
- One outage is one incident: it opens on the transition to DOWN and closes on the first
  success, and a partial unique index guarantees there is never a second open one.
- Due monitors are claimed with SELECT ... FOR UPDATE SKIP LOCKED, so two running instances
  never check the same monitor twice.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulse.models import Check, Incident, Monitor, State
from pulse.safety import Resolver, UnsafeUrl, assert_public, system_resolver

log = logging.getLogger("pulse.checker")

USER_AGENT = "PulseMonitor/1.0 (+https://github.com/zaremifa-cell/pulse)"


@dataclass(frozen=True)
class Result:
    ok: bool
    status_code: int | None
    response_ms: int | None
    error: str | None


def now() -> datetime:
    return datetime.now(UTC)


async def probe(client: httpx.AsyncClient, url: str, timeout: float, resolve: Resolver = system_resolver) -> Result:
    """One HTTP GET. 2xx and 3xx count as up; anything else, or no answer in time, as down."""
    try:
        await assert_public(url, resolve)
    except UnsafeUrl as exc:
        return Result(False, None, None, str(exc))

    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            response = await client.get(url, follow_redirects=False)
    except TimeoutError:
        return Result(False, None, None, f"No answer within {timeout:g}s")
    except httpx.HTTPError as exc:
        return Result(False, None, None, f"{type(exc).__name__}: {exc}".strip(": ") or type(exc).__name__)
    elapsed = int((time.perf_counter() - started) * 1000)
    ok = response.status_code < 400
    return Result(ok, response.status_code, elapsed, None if ok else f"HTTP {response.status_code}")


def apply(monitor: Monitor, result: Result, at: datetime, session: AsyncSession) -> None:
    """Record the check and move the monitor's state machine forward."""
    session.add(
        Check(
            monitor_id=monitor.id,
            checked_at=at,
            ok=result.ok,
            status_code=result.status_code,
            response_ms=result.response_ms,
            error=result.error,
        )
    )
    monitor.last_checked_at = at
    monitor.next_check_at = at + timedelta(seconds=monitor.interval_seconds)

    if result.ok:
        if monitor.state == State.DOWN:
            for incident in monitor.incidents:
                if incident.resolved_at is None:
                    incident.resolved_at = at
        monitor.consecutive_failures = 0
        monitor.state = State.UP
        return

    monitor.consecutive_failures += 1
    if monitor.consecutive_failures < monitor.failure_threshold:
        monitor.state = State.DEGRADED
    elif monitor.state != State.DOWN:
        monitor.state = State.DOWN
        session.add(
            Incident(
                monitor_id=monitor.id,
                started_at=at,
                cause=result.error or "Check failed",
                failed_checks=monitor.consecutive_failures,
            )
        )
    else:
        for incident in monitor.incidents:
            if incident.resolved_at is None:
                incident.failed_checks = monitor.consecutive_failures


async def run_due(
    sessions: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
    *,
    resolve: Resolver = system_resolver,
    max_concurrency: int = 20,
    at: datetime | None = None,
) -> int:
    """Check every monitor that is due. Returns how many were checked."""
    at = at or now()
    async with sessions() as session, session.begin():
        due = (
            await session.scalars(
                select(Monitor)
                .where(Monitor.next_check_at <= at)
                .order_by(Monitor.next_check_at)
                .limit(200)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not due:
            return 0
        for monitor in due:
            await session.refresh(monitor, ["incidents"])

        gate = asyncio.Semaphore(max_concurrency)

        async def one(monitor: Monitor) -> Result:
            async with gate:
                return await probe(client, monitor.url, monitor.timeout_seconds, resolve)

        results = await asyncio.gather(*(one(m) for m in due))
        for monitor, result in zip(due, results, strict=True):
            apply(monitor, result, at, session)
    return len(due)


async def prune(sessions: async_sessionmaker[AsyncSession], retention_days: int) -> None:
    async with sessions() as session, session.begin():
        await session.execute(delete(Check).where(Check.checked_at < now() - timedelta(days=retention_days)))


async def loop(
    sessions: async_sessionmaker[AsyncSession], tick_seconds: float, max_concurrency: int, retention_days: int
) -> None:
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        ticks = 0
        while True:
            try:
                await run_due(sessions, client, max_concurrency=max_concurrency)
                if ticks % 720 == 0:  # about once an hour at the default tick
                    await prune(sessions, retention_days)
            except Exception:  # keep checking even if one round fails
                log.exception("check round failed")
            ticks += 1
            await asyncio.sleep(tick_seconds)
