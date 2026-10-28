import os

# Must be set before pulse is imported: settings are read at import time.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/pulse_test")
os.environ["RUN_CHECKER"] = "false"
os.environ["SEED_DEMO"] = "false"

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pulse import api
from pulse.config import async_database_url, settings
from pulse.db import Base


@pytest.fixture
async def sessions(monkeypatch):
    url, connect_args = async_database_url(settings.database_url)
    engine = create_async_engine(url, connect_args=connect_args, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionFactory", factory)
    yield factory
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS checks, incidents, monitors CASCADE"))
    await engine.dispose()


async def public_resolver(host: str) -> list[str]:
    return ["93.184.215.14"]
