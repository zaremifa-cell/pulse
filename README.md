# Pulse — uptime monitoring with a status page

Pulse checks websites every minute, records how fast they answer, opens an incident when one
goes down and closes it when it comes back. A public status page shows each site's state, a
24-hour timeline, uptime for 24 hours and 7 days, and p95 response time.

Built with **Python 3.14, FastAPI, SQLAlchemy 2 (async), PostgreSQL, Alembic and httpx**.

**Live demo:** https://pulse-qrke.onrender.com (free server: the first visit can take up to a minute) · API docs at `/docs`

## How it decides a site is down

| Situation | What happens |
|---|---|
| One slow or failed answer | The site is **degraded**, not down. It is **down** only after 3 failures in a row (configurable per monitor), so one blip doesn't raise a false alarm. |
| The site stays down for an hour | Still **one** incident, with a growing failed-check count. A partial unique index in PostgreSQL makes a second open incident for the same monitor impossible. |
| The site comes back | The first successful check closes the incident and resets the counter. |
| One site hangs | Each check has its own timeout and all due checks run concurrently (`asyncio.gather` with a concurrency limit), so one hanging site never delays the others. |
| Two Pulse instances run at once | Due monitors are claimed with `SELECT … FOR UPDATE SKIP LOCKED`, so no monitor is checked twice. |
| The monitor itself was offline | Those periods show as "no data" and are left out of the uptime figure instead of being counted as up or down. |
| Someone adds `http://169.254.169.254/` or `localhost` | Refused. Every address the host resolves to must be public, and this is checked again before every request, so a DNS record changed later can't reach the private network either (SSRF protection). |

## Code map

```
src/pulse/checker.py   probing, the up/degraded/down state machine, incidents, the check loop
src/pulse/safety.py    URL validation and private-network (SSRF) protection
src/pulse/stats.py     uptime, p95 and the 24-hour timeline
src/pulse/api.py       FastAPI routes, demo seed data, background checker on startup
src/pulse/static/      the status page (plain HTML, CSS and JavaScript)
migrations/            Alembic migrations
tests/                 pytest: fake sites through httpx.MockTransport, a real PostgreSQL
```

## Run it

Requires Python 3.14, [uv](https://docs.astral.sh/uv/) and PostgreSQL.

```bash
uv sync
createdb pulse
DATABASE_URL=postgresql://localhost/pulse uv run alembic upgrade head
DATABASE_URL=postgresql://localhost/pulse uv run pulse
# http://localhost:8000
```

Or with Docker: `docker compose up --build`.

## Tests

```bash
createdb pulse_test
uv run pytest
```

32 tests. The checker tests use a fake internet (`httpx.MockTransport`) with sites that answer,
fail, refuse connections or hang, and run against a real PostgreSQL so that row locking and the
partial unique index are tested for real. GitHub Actions runs Ruff, the migrations and the tests
on every push.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/monitors` | All monitors with state, uptime, p95 and timeline |
| POST | `/api/monitors` | Add a monitor (`name`, `url`, optional interval, timeout, failure threshold) |
| DELETE | `/api/monitors/{id}` | Stop monitoring |
| GET | `/api/monitors/{id}/checks` | Latest raw checks |
| GET | `/api/incidents` | Latest incidents |

## Limits

The demo runs on a free server that sleeps when nobody visits, so checks only run while it is
awake; the gaps are shown honestly as "no data". There is no login or alerting by e-mail; the
demo is limited to 25 monitors and keeps 8 days of checks.
