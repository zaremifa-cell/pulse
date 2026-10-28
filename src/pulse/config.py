from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://localhost/pulse"
    port: int = 8000
    run_checker: bool = True
    tick_seconds: float = 5.0
    max_concurrency: int = 20
    max_monitors: int = 25
    retention_days: int = 8
    seed_demo: bool = True


settings = Settings()


def async_database_url(url: str) -> tuple[str, dict]:
    """Turn a plain Postgres URL (as Neon or Render give it) into an asyncpg URL plus connect args.

    asyncpg rejects libpq-only query options such as channel_binding, so the query string is
    reduced to what asyncpg understands and sslmode becomes its ssl argument.
    """
    parts = urlsplit(url)
    scheme = "postgresql+asyncpg"
    query = dict(parse_qsl(parts.query))
    connect_args: dict = {}
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = "require"
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)), connect_args
