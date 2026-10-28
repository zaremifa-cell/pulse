from datetime import timedelta

import httpx
import pytest

from pulse import api, checker, stats
from pulse.models import Check, Monitor
from pulse.safety import UnsafeUrl


async def seed_checks(sessions, pattern, start):
    async with sessions() as s, s.begin():
        monitor = Monitor(name="m", url="https://m.test/")
        s.add(monitor)
        await s.flush()
        for minutes, ok in pattern:
            s.add(Check(monitor_id=monitor.id, checked_at=start + timedelta(minutes=minutes), ok=ok, response_ms=100))
    return monitor.id


async def test_uptime_ignores_time_without_checks(sessions):
    end = checker.now()
    # 3 good checks and 1 bad one in the last hour; nothing for the 23 hours before.
    mid = await seed_checks(sessions, [(0, True), (1, True), (2, False), (3, True)], end - timedelta(minutes=30))
    async with sessions() as s:
        assert await stats.uptime(s, mid, end - timedelta(hours=24)) == 75.0
        line = await stats.timeline(s, mid, end)
    assert line.count("none") == 47 and line[-1] == "down"


async def test_uptime_is_unknown_without_any_checks(sessions):
    mid = await seed_checks(sessions, [], checker.now())
    async with sessions() as s:
        assert await stats.uptime(s, mid, checker.now() - timedelta(days=7)) is None


@pytest.fixture
async def client(sessions, monkeypatch):
    async def fake_assert_public(url, resolve=None):
        if "internal" in url:
            raise UnsafeUrl("internal.test points to a private or reserved address (10.0.0.1).")

    monkeypatch.setattr(api, "assert_public", fake_assert_public)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as c:
        yield c


async def test_create_list_and_delete_a_monitor(client):
    created = await client.post("/api/monitors", json={"name": "Site", "url": "https://site.example/"})
    assert created.status_code == 201 and created.json()["state"] == "unknown"

    listed = (await client.get("/api/monitors")).json()
    assert [m["name"] for m in listed] == ["Site"] and len(listed[0]["timeline"]) == 48

    assert (await client.delete(f"/api/monitors/{created.json()['id']}")).status_code == 204
    assert (await client.get("/api/monitors")).json() == []


async def test_the_same_address_twice_is_refused(client):
    await client.post("/api/monitors", json={"name": "A", "url": "https://site.example/"})
    again = await client.post("/api/monitors", json={"name": "B", "url": "https://site.example/"})
    assert again.status_code == 409


async def test_private_addresses_and_bad_schemes_are_refused(client):
    assert (await client.post("/api/monitors", json={"name": "x", "url": "https://internal.test/"})).status_code == 422
    assert (await client.post("/api/monitors", json={"name": "x", "url": "file:///etc/passwd"})).status_code == 422


async def test_the_demo_limit_is_enforced(client, monkeypatch):
    monkeypatch.setattr(api.settings, "max_monitors", 1)
    await client.post("/api/monitors", json={"name": "A", "url": "https://a.example/"})
    over = await client.post("/api/monitors", json={"name": "B", "url": "https://b.example/"})
    assert over.status_code == 409 and "limited to 1" in over.json()["detail"]


async def test_unknown_monitor_is_404(client):
    assert (await client.get("/api/monitors/999/checks")).status_code == 404
