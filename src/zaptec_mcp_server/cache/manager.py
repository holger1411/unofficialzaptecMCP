"""TTL-based response cache with per-key single-flight.

Cache keys are derived from the tool name plus a stable representation of the
tool's arguments. Failures are never cached: only successful loader returns
populate the store. A TTL of 0 disables caching for that single call.

Concurrent callers for the same key share one in-flight load. The load runs in
its own task, so a cancelled caller does not cancel it for the others; a failed
load raises in every waiter and the next call starts a new one. `invalidate()`
and `clear()` detach in-flight loads: their callers still get the result, but
it is not stored. Expired entries are pruned on every call and `max_entries`
bounds the store (oldest entries are evicted first).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

_Loader = Callable[[], Awaitable[Any]]
_Key = tuple[str, str]

DEFAULT_MAX_ENTRIES = 128


def _stable_key(tool: str, args: dict[str, Any]) -> _Key:
    return (tool, json.dumps(args, sort_keys=True, default=str))


class CacheManager:
    """In-process TTL cache. Single asyncio loop, no thread safety needed."""

    def __init__(
        self,
        enabled: bool = True,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._enabled = enabled
        self._max_entries = max_entries
        self._clock = clock
        # Insertion-ordered: the first key is the oldest entry.
        self._store: dict[_Key, tuple[float, Any]] = {}
        self._inflight: dict[_Key, asyncio.Future[Any]] = {}
        # Bumped by invalidate()/clear(); a load only stores if nothing changed meanwhile.
        self._generations: dict[str, int] = {}
        self._epoch = 0

    def __len__(self) -> int:
        return len(self._store)

    async def get_or_load(
        self,
        tool: str,
        args: dict[str, Any],
        ttl: float,
        loader: _Loader,
    ) -> Any:
        if not self._enabled or ttl <= 0:
            return await loader()

        key = _stable_key(tool, args)
        self._prune(self._clock())
        cached = self._store.get(key)
        if cached is not None:
            return cached[1]

        pending = self._inflight.get(key)
        if pending is None:
            pending = asyncio.ensure_future(loader())
            self._inflight[key] = pending
            pending.add_done_callback(partial(self._finish, key, ttl, self._token(tool)))
        # shield: cancelling this caller must not cancel the load for other waiters.
        return await asyncio.shield(pending)

    def invalidate(self, tool: str) -> None:
        """Drop every cached entry for one tool and detach its in-flight loads."""
        self._generations[tool] = self._generations.get(tool, 0) + 1
        for key in [k for k in self._store if k[0] == tool]:
            del self._store[key]
        for key in [k for k in self._inflight if k[0] == tool]:
            del self._inflight[key]

    def clear(self) -> None:
        self._epoch += 1
        self._store.clear()
        self._inflight.clear()

    # -- internals ------------------------------------------------------------

    def _token(self, tool: str) -> tuple[int, int]:
        return (self._epoch, self._generations.get(tool, 0))

    def _finish(
        self, key: _Key, ttl: float, token: tuple[int, int], fut: asyncio.Future[Any]
    ) -> None:
        if self._inflight.get(key) is fut:
            del self._inflight[key]
        if fut.cancelled():
            return
        if fut.exception() is not None:  # also marks the exception as retrieved
            return
        if self._token(key[0]) != token:
            return  # invalidated while loading: the result may be stale
        self._store.pop(key, None)
        self._store[key] = (self._clock() + ttl, fut.result())
        while len(self._store) > self._max_entries:
            del self._store[next(iter(self._store))]

    def _prune(self, now: float) -> None:
        for key in [k for k, (expires_at, _) in self._store.items() if expires_at <= now]:
            del self._store[key]
