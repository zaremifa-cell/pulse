import asyncio
import contextlib
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pulse import checker, stats
from pulse.config import settings
from pulse.db import SessionFactory
from pulse.models import Check, Incident, Monitor
from pulse.safety import UnsafeUrl, assert_public, parse_url

STATIC = Path(__file__).parent / "static"

DEMO_MONITORS = [
    ("Portfolio", "https://zlatko-anastasov-portfolio.vercel.app/"),
    ("GitHub", "https://github.com/"),
    ("Python.org", "https://www.python.org/"),
    ("Wikipedia", "https://www.wikipedia.org/"),
    ("Example", "https://example.com/"),
    # A name that can never resolve, so the demo always shows what an outage looks like.
    ("Broken on purpose", "https://status.does-not-exist.invalid/"),
]


async def seed_demo() -> None:
    async with SessionFactory() as session, session.begin():
        if await session.scalar(select(func.count()).select_from(Monitor)):
            return
        session.add_all(Monitor(name=name, url=url) for name, url in DEMO_MONITORS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.seed_demo:
        await seed_demo()
    task = None
    if settings.run_checker:
        task = asyncio.create_task(
            checker.loop(SessionFactory, settings.tick_seconds, settings.max_concurrency, settings.retention_days)
        )
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Pulse", summary="Uptime monitoring with a status page", lifespan=lifespan)


async def get_session():
    async with SessionFactory() as session:
        yield session


class MonitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=500)
    interval_seconds: int = Field(60, ge=30, le=3600)
    timeout_seconds: float = Field(10, ge=1, le=30)
    failure_threshold: int = Field(3, ge=1, le=10)

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        try:
            parse_url(value)
        except UnsafeUrl as exc:
            raise ValueError(str(exc)) from exc
        return value.strip()


class MonitorOut(BaseModel):
    id: int
    name: str
    url: str
    state: str
    interval_seconds: int
    failure_threshold: int
    consecutive_failures: int
    last_checked_at: datetime | None
    last_response_ms: int | None
    last_error: str | None
    uptime_24h: float | None
    uptime_7d: float | None
    p95_ms_24h: int | None
    timeline: list[str]


async def describe(session: AsyncSession, monitor: Monitor, at: datetime) -> MonitorOut:
    last = await session.scalar(select(Check).where(Check.monitor_id == monitor.id).order_by(Check.checked_at.desc()).limit(1))
    return MonitorOut(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        state=monitor.state,
        interval_seconds=monitor.interval_seconds,
        failure_threshold=monitor.failure_threshold,
        consecutive_failures=monitor.consecutive_failures,
        last_checked_at=monitor.last_checked_at,
        last_response_ms=last.response_ms if last else None,
        last_error=last.error if last else None,
        uptime_24h=await stats.uptime(session, monitor.id, at - timedelta(hours=24)),
        uptime_7d=await stats.uptime(session, monitor.id, at - timedelta(days=7)),
        p95_ms_24h=await stats.p95_ms(session, monitor.id, at - timedelta(hours=24)),
        timeline=await stats.timeline(session, monitor.id, at),
    )


@app.get("/api/monitors", response_model=list[MonitorOut])
async def list_monitors(session: AsyncSession = Depends(get_session)):
    at = checker.now()
    monitors = (await session.scalars(select(Monitor).order_by(Monitor.id))).all()
    return [await describe(session, m, at) for m in monitors]


@app.post("/api/monitors", response_model=MonitorOut, status_code=201)
async def create_monitor(data: MonitorIn, session: AsyncSession = Depends(get_session)):
    try:
        await assert_public(data.url)
    except UnsafeUrl as exc:
        raise HTTPException(422, str(exc)) from exc
    if await session.scalar(select(func.count()).select_from(Monitor)) >= settings.max_monitors:
        raise HTTPException(409, f"The demo is limited to {settings.max_monitors} monitors. Delete one first.")
    monitor = Monitor(**data.model_dump())
    session.add(monitor)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "That address is already monitored.") from exc
    return await describe(session, monitor, checker.now())


@app.delete("/api/monitors/{monitor_id}", status_code=204)
async def delete_monitor(monitor_id: int, session: AsyncSession = Depends(get_session)):
    monitor = await session.get(Monitor, monitor_id)
    if not monitor:
        raise HTTPException(404, "Monitor not found.")
    await session.delete(monitor)
    await session.commit()


@app.get("/api/monitors/{monitor_id}/checks")
async def monitor_checks(monitor_id: int, limit: int = Query(50, ge=1, le=500), session: AsyncSession = Depends(get_session)):
    if not await session.get(Monitor, monitor_id):
        raise HTTPException(404, "Monitor not found.")
    rows = (
        await session.scalars(select(Check).where(Check.monitor_id == monitor_id).order_by(Check.checked_at.desc()).limit(limit))
    ).all()
    return [
        {"checked_at": c.checked_at, "ok": c.ok, "status_code": c.status_code, "response_ms": c.response_ms, "error": c.error}
        for c in rows
    ]


@app.get("/api/incidents")
async def incidents(limit: int = Query(20, ge=1, le=100), session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(Incident, Monitor.name).join(Monitor).order_by(Incident.started_at.desc()).limit(limit))
    ).all()
    return [
        {
            "id": i.id,
            "monitor": name,
            "started_at": i.started_at,
            "resolved_at": i.resolved_at,
            "cause": i.cause,
            "failed_checks": i.failed_checks,
            "duration_seconds": int(((i.resolved_at or checker.now()) - i.started_at).total_seconds()),
        }
        for i, name in rows
    ]


@app.get("/up")
async def health():
    return {"ok": True}


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
