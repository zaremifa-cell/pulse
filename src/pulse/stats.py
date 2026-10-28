"""Uptime figures and the 24-hour timeline on the status page.

Time with no checks at all (for example while the free demo server was asleep) is shown as
"no data" and left out of the uptime percentage. Counting it as up would flatter the site;
counting it as down would blame the site for the monitor's own absence.
"""

from datetime import datetime, timedelta

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.models import Check


async def uptime(session: AsyncSession, monitor_id: int, since: datetime) -> float | None:
    total, good = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(cast(Check.ok, Integer)), 0)).where(
                Check.monitor_id == monitor_id, Check.checked_at >= since
            )
        )
    ).one()
    return None if total == 0 else round(100 * good / total, 2)


async def p95_ms(session: AsyncSession, monitor_id: int, since: datetime) -> int | None:
    value = await session.scalar(
        select(func.percentile_cont(0.95).within_group(Check.response_ms)).where(
            Check.monitor_id == monitor_id, Check.checked_at >= since, Check.ok.is_(True)
        )
    )
    return None if value is None else int(value)


async def timeline(session: AsyncSession, monitor_id: int, end: datetime, buckets: int = 48, hours: int = 24) -> list[str]:
    """Each bucket is 'up', 'down' (any failed check) or 'none' (no checks), oldest first."""
    size = timedelta(hours=hours) / buckets
    start = end - timedelta(hours=hours)
    rows = (
        await session.execute(select(Check.checked_at, Check.ok).where(Check.monitor_id == monitor_id, Check.checked_at >= start))
    ).all()
    result = ["none"] * buckets
    for checked_at, ok in rows:
        index = min(int((checked_at - start) / size), buckets - 1)
        if not ok:
            result[index] = "down"
        elif result[index] == "none":
            result[index] = "up"
    return result
