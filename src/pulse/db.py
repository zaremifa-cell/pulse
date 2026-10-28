from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from pulse.config import async_database_url, settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str = settings.database_url):
    async_url, connect_args = async_database_url(url)
    return create_async_engine(async_url, connect_args=connect_args, pool_pre_ping=True)


engine = make_engine()
SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
