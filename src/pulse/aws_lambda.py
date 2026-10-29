"""Entry points for running Pulse on AWS Lambda.

Two functions share this package:
- ``http_handler`` serves the status page and REST API behind a Lambda function URL;
- ``check_handler`` runs one round of checks, started every minute by EventBridge Scheduler.

The database address comes from the encrypted DATABASE_URL environment variable, or, when
DATABASE_URL_PARAMETER names one, from an SSM SecureString read once per container (accounts on
the AWS Free plan cannot write SSM parameters, so the stack in infra/ uses the environment).
Each container keeps one event loop for its whole
life: the connection pool belongs to that loop and is reused across invocations.
"""

import asyncio
import base64
import os

_loop = asyncio.new_event_loop()


def _load_database_url() -> None:
    name = os.environ.get("DATABASE_URL_PARAMETER")
    if not name or "DATABASE_URL" in os.environ:
        return
    import boto3

    value = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    os.environ["DATABASE_URL"] = value


_load_database_url()

# Imported after the database address is in the environment: settings are read at import time.
import httpx  # noqa: E402

from pulse import checker  # noqa: E402
from pulse.api import app, seed_demo  # noqa: E402
from pulse.config import settings  # noqa: E402
from pulse.db import SessionFactory  # noqa: E402

_client: httpx.AsyncClient | None = None
_asgi: httpx.AsyncClient | None = None


async def _handle_http(event: dict) -> dict:
    global _asgi
    # The app is called in-process through httpx's ASGI transport; no web server is needed.
    _asgi = _asgi or httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://pulse.lambda")
    http = event["requestContext"]["http"]
    body = event.get("body") or ""
    content = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    headers = dict(event.get("headers") or {})
    if event.get("cookies"):
        headers["cookie"] = "; ".join(event["cookies"])
    response = await _asgi.request(
        http["method"], event.get("rawPath", "/"), params=event.get("rawQueryString") or None, headers=headers, content=content
    )
    return {
        "statusCode": response.status_code,
        "headers": {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "transfer-encoding")},
        "body": base64.b64encode(response.content).decode(),
        "isBase64Encoded": True,
    }


def http_handler(event: dict, context: object) -> dict:
    return _loop.run_until_complete(_handle_http(event))


async def _check_round() -> int:
    global _client
    _client = _client or httpx.AsyncClient(headers={"User-Agent": checker.USER_AGENT})
    if settings.seed_demo:
        await seed_demo()
    checked = await checker.run_due(SessionFactory, _client, max_concurrency=settings.max_concurrency)
    if checker.now().minute == 0:  # about once an hour
        await checker.prune(SessionFactory, settings.retention_days)
    return checked


def check_handler(event: dict, context: object) -> dict:
    return {"checked": _loop.run_until_complete(_check_round())}
