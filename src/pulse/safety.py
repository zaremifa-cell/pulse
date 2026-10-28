"""Stops the public demo from being used to probe private networks (SSRF).

Anyone can add a URL, so before every request the host is resolved and every address it
resolves to must be public. Checking at request time, not only when the monitor is created,
also covers a DNS record that is changed later to point inside the network.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], Awaitable[list[str]]]


class UnsafeUrl(ValueError):
    pass


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def parse_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrl("Only http:// and https:// addresses can be monitored.")
    if not parts.hostname:
        raise UnsafeUrl("The address has no host name.")
    if parts.username or parts.password:
        raise UnsafeUrl("Addresses with a user name or password are not allowed.")
    return parts.hostname


async def assert_public(url: str, resolve: Resolver = system_resolver) -> None:
    host = parse_url(url)
    try:
        addresses = await resolve(host)
    except OSError as exc:
        raise UnsafeUrl(f"Could not resolve {host}.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeUrl(f"{host} points to a private or reserved address ({ip}).")
