"""Pulse: uptime monitoring with a public status page."""


def main() -> None:
    import uvicorn

    from pulse.config import settings

    uvicorn.run("pulse.api:app", host="0.0.0.0", port=settings.port, proxy_headers=True, forwarded_allow_ips="*")
