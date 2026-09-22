import pytest

from zaptec_mcp_server.cache.manager import CacheManager


async def test_caches_within_ttl() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager()
    assert await cache.get_or_load("t", {"a": 1}, ttl=60, loader=loader) == 1
    assert await cache.get_or_load("t", {"a": 1}, ttl=60, loader=loader) == 1
    assert await cache.get_or_load("t", {"a": 2}, ttl=60, loader=loader) == 2


async def test_ttl_zero_or_disabled_bypasses() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager()
    assert await cache.get_or_load("t", {}, ttl=0, loader=loader) == 1
    assert await cache.get_or_load("t", {}, ttl=0, loader=loader) == 2
    off = CacheManager(enabled=False)
    assert await off.get_or_load("t", {}, ttl=60, loader=loader) == 3
    assert await off.get_or_load("t", {}, ttl=60, loader=loader) == 4


async def test_failures_not_cached() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("fail")
        return calls

    cache = CacheManager()
    with pytest.raises(RuntimeError):
        await cache.get_or_load("t", {}, ttl=60, loader=loader)
    assert await cache.get_or_load("t", {}, ttl=60, loader=loader) == 2


async def test_invalidate_by_tool() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager()
    await cache.get_or_load("status", {"c": "1"}, ttl=60, loader=loader)
    await cache.get_or_load("other", {}, ttl=60, loader=loader)
    cache.invalidate("status")
    assert await cache.get_or_load("status", {"c": "1"}, ttl=60, loader=loader) == 3
    assert await cache.get_or_load("other", {}, ttl=60, loader=loader) == 2
