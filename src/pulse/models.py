from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pulse.db import Base


class State(StrEnum):
    UNKNOWN = "unknown"  # not checked yet
    UP = "up"
    DEGRADED = "degraded"  # failing, but not yet failure_threshold times in a row
    DOWN = "down"


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(String(500), unique=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[float] = mapped_column(default=10.0)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3)
    state: Mapped[str] = mapped_column(String(16), default=State.UNKNOWN)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    checks: Mapped[list[Check]] = relationship(back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True)
    incidents: Mapped[list[Incident]] = relationship(back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (Index("ix_monitors_next_check_at", "next_check_at"),)


class Check(Base):
    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    monitor: Mapped[Monitor] = relationship(back_populates="checks")

    __table_args__ = (Index("ix_checks_monitor_checked_at", "monitor_id", "checked_at"),)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cause: Mapped[str] = mapped_column(Text)
    failed_checks: Mapped[int] = mapped_column(Integer)

    monitor: Mapped[Monitor] = relationship(back_populates="incidents")

    # At most one open incident per monitor, enforced by the database rather than by hope.
    __table_args__ = (
        Index(
            "uq_incidents_one_open_per_monitor",
            "monitor_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )
