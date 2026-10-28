import pytest

from pulse.config import async_database_url
from pulse.safety import UnsafeUrl, assert_public


def resolver(*addresses):
    async def resolve(host):
        return list(addresses)

    return resolve


async def failing(host):
    raise OSError("no such host")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fd00::1", "0.0.0.0"])
async def test_private_and_reserved_addresses_are_refused(address):
    with pytest.raises(UnsafeUrl, match="private or reserved"):
        await assert_public("https://site.test/", resolver(address))


async def test_one_private_address_among_public_ones_is_enough_to_refuse():
    with pytest.raises(UnsafeUrl):
        await assert_public("https://site.test/", resolver("93.184.215.14", "10.1.2.3"))


async def test_public_address_is_allowed():
    await assert_public("https://site.test/", resolver("93.184.215.14"))


@pytest.mark.parametrize(
    "url,message",
    [
        ("ftp://site.test/", "Only http"),
        ("https:///nohost", "no host"),
        ("https://user:pw@site.test/", "user name or password"),
    ],
)
async def test_bad_urls_are_refused(url, message):
    with pytest.raises(UnsafeUrl, match=message):
        await assert_public(url, resolver("93.184.215.14"))


async def test_unresolvable_host_is_reported():
    with pytest.raises(UnsafeUrl, match="Could not resolve"):
        await assert_public("https://nowhere.test/", failing)


def test_neon_style_url_becomes_an_asyncpg_url():
    url, args = async_database_url("postgresql://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require")
    assert url == "postgresql+asyncpg://u:p@ep-x.neon.tech/db"
    assert args == {"ssl": "require"}
