"""TTL-based response cache.

Cache keys are derived from the tool name plus a stable representation of the
tool's arguments. Failures are never cached: only successful loader returns
populate the store. A TTL of 0 disables caching for that single call.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

_Loader = Callable[[], Awaitable[Any]]


def _stable_key(tool: str, args: dict[str, Any]) -> Hashable:
    return (tool, json.dumps(args, sort_keys=True, default=str))


class CacheManager:
    """In-process TTL cache. Single asyncio loop, no thread safety needed."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._store: dict[Hashable, tuple[float, Any]] = {}

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
        now = time.monotonic()
        cached = self._store.get(key)
        if cached is not None:
            expires_at, value = cached
            if expires_at > now:
                return value
            del self._store[key]

        value = await loader()  # exceptions propagate; nothing is cached
        self._store[key] = (now + ttl, value)
        return value

    def invalidate(self, tool: str) -> None:
        """Drop every cached entry for one tool."""
        for key in [k for k in self._store if isinstance(k, tuple) and k[0] == tool]:
            del self._store[key]

    def clear(self) -> None:
        self._store.clear()
