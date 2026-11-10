from __future__ import annotations

import asyncio

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


async def test_expires_after_ttl() -> None:
    now = [100.0]
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager(clock=lambda: now[0])
    assert await cache.get_or_load("t", {}, ttl=10, loader=loader) == 1
    now[0] += 9.9
    assert await cache.get_or_load("t", {}, ttl=10, loader=loader) == 1
    now[0] += 0.2
    assert await cache.get_or_load("t", {}, ttl=10, loader=loader) == 2


# -- single-flight ------------------------------------------------------------


async def test_concurrent_callers_share_one_load() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return calls

    cache = CacheManager()
    results = await asyncio.gather(
        *(cache.get_or_load("t", {"a": 1}, ttl=60, loader=loader) for _ in range(5))
    )
    assert results == [1, 1, 1, 1, 1]
    assert calls == 1


async def test_failed_load_propagates_to_all_waiters_and_is_retried() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        if calls == 1:
            raise RuntimeError("boom")
        return calls

    cache = CacheManager()
    results = await asyncio.gather(
        *(cache.get_or_load("t", {}, ttl=60, loader=loader) for _ in range(3)),
        return_exceptions=True,
    )
    assert calls == 1
    assert all(isinstance(r, RuntimeError) for r in results)
    assert await cache.get_or_load("t", {}, ttl=60, loader=loader) == 2
    assert await cache.get_or_load("t", {}, ttl=60, loader=loader) == 2


async def test_invalidate_during_load_does_not_store_stale_result() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "stale"

    async def fresh() -> str:
        nonlocal calls
        calls += 1
        return "fresh"

    cache = CacheManager()
    first = asyncio.ensure_future(cache.get_or_load("status", {}, ttl=60, loader=slow))
    await started.wait()
    cache.invalidate("status")
    # A caller after invalidate() must not join the stale in-flight load.
    assert await cache.get_or_load("status", {}, ttl=60, loader=fresh) == "fresh"
    release.set()
    assert await first == "stale"  # the original caller still gets its own result
    assert await cache.get_or_load("status", {}, ttl=60, loader=fresh) == "fresh"
    assert calls == 2


async def test_clear_during_load_does_not_store_result() -> None:
    release = asyncio.Event()

    async def slow() -> str:
        await release.wait()
        return "old"

    async def fresh() -> str:
        return "new"

    cache = CacheManager()
    first = asyncio.ensure_future(cache.get_or_load("t", {}, ttl=60, loader=slow))
    await asyncio.sleep(0)
    cache.clear()
    release.set()
    assert await first == "old"
    assert await cache.get_or_load("t", {}, ttl=60, loader=fresh) == "new"


async def test_cancelled_caller_does_not_break_other_waiters() -> None:
    release = asyncio.Event()

    async def slow() -> str:
        await release.wait()
        return "v"

    cache = CacheManager()
    a = asyncio.ensure_future(cache.get_or_load("t", {}, ttl=60, loader=slow))
    b = asyncio.ensure_future(cache.get_or_load("t", {}, ttl=60, loader=slow))
    await asyncio.sleep(0)
    a.cancel()
    release.set()
    assert await b == "v"
    with pytest.raises(asyncio.CancelledError):
        await a


# -- bounded size -------------------------------------------------------------


async def test_expired_entries_are_pruned() -> None:
    now = [0.0]

    async def loader() -> int:
        return 1

    cache = CacheManager(clock=lambda: now[0])
    for day in range(20):
        await cache.get_or_load("history", {"day": day}, ttl=10, loader=loader)
    assert len(cache) == 20
    now[0] += 11
    await cache.get_or_load("status", {}, ttl=10, loader=loader)
    assert len(cache) == 1


async def test_max_entries_evicts_oldest() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager(max_entries=3)
    for i in range(5):
        await cache.get_or_load("history", {"i": i}, ttl=60, loader=loader)
    assert len(cache) == 3
    assert await cache.get_or_load("history", {"i": 4}, ttl=60, loader=loader) == 5  # kept
    assert await cache.get_or_load("history", {"i": 0}, ttl=60, loader=loader) == 6  # evicted


def test_max_entries_must_be_positive() -> None:
    with pytest.raises(ValueError):
        CacheManager(max_entries=0)
