"""Tool implementations: caching, guards and orchestration over ZaptecClient."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, TypeAlias, cast
from zoneinfo import ZoneInfo

from .cache.manager import CacheManager
from .config import ServerConfig
from .utils.errors import ZaptecGuardError
from .zaptec.client import CMD_PAUSE, CMD_RESUME, ZaptecClient
from .zaptec.formatters import (
    format_history,
    format_installation,
    format_status,
    summarize_mode,
)
from .zaptec.observations import Mode, Obs, StateMap, field
from .zaptec.timeranges import resolve_range, validate_custom_dates

log = logging.getLogger(__name__)

TTL_STATUS = 15.0
TTL_INSTALLATION = 300.0
TTL_HISTORY = 300.0


def _tz_of(installation: dict[str, Any]) -> ZoneInfo:
    name = field(installation, "TimeZoneIanaName")
    if isinstance(name, str) and name:
        try:
            return ZoneInfo(name)
        except Exception:  # unknown zone name from the API
            log.warning("unknown timezone %r, falling back to UTC", name)
    return ZoneInfo("UTC")


def _parse_date(s: str | None) -> date | None:
    return None if s is None else date.fromisoformat(s)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _finite_number(value: Any) -> float | None:
    """`value` as float if it is a real, finite number (bool excluded), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


# -- pause / resume -------------------------------------------------------------

# Pseudo state for "connected_finished with final_stop_active": paused by app or server.
_PAUSED = "paused"
_UNKNOWN_STATE = "the charger state is unknown"

_StateKey: TypeAlias = int | str | None


def _state_key(mode: Mapping[str, Any]) -> _StateKey:
    code = mode["code"]
    if code == Mode.FINISHED and mode["final_stop_active"]:
        return _PAUSED
    return cast(_StateKey, code)


@dataclass(frozen=True)
class _CommandSpec:
    name: str
    command_id: int
    allowed_state: _StateKey
    refusals: Mapping[_StateKey, str]
    note: str


_PAUSE = _CommandSpec(
    name="pause",
    command_id=CMD_PAUSE,
    allowed_state=Mode.CHARGING,
    refusals={
        _PAUSED: "charging is already paused",
        Mode.FINISHED: (
            "the vehicle is connected but not charging (finished or stopped by the vehicle)"
        ),
        Mode.DISCONNECTED: "no vehicle is connected",
        Mode.REQUESTING: (
            "the charger is waiting for authorization or for the vehicle to request power"
        ),
    },
    note=(
        "Pause requested. Within a few seconds the charger reports mode "
        "connected_finished with final_stop_active=true."
    ),
)

_RESUME = _CommandSpec(
    name="resume",
    command_id=CMD_RESUME,
    allowed_state=_PAUSED,
    refusals={
        Mode.CHARGING: "the charger is already charging",
        Mode.DISCONNECTED: "no vehicle is connected",
        Mode.REQUESTING: (
            "the charger is waiting for authorization or for the vehicle; "
            "resume only works for a paused session"
        ),
        Mode.FINISHED: (
            "the session is not paused by the charger; the vehicle stopped charging "
            "itself (full battery, schedule or vehicle app)"
        ),
    },
    note="Resume requested. Charging restarts within seconds if the vehicle accepts power.",
)


class ZaptecTools:
    def __init__(
        self,
        *,
        client: ZaptecClient,
        cache: CacheManager,
        cfg: ServerConfig,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client
        self._cache = cache
        self._cfg = cfg
        self._clock = clock
        self._now = now
        self._last_current_update: float | None = None
        # Serializes the rate-guard check with the update it protects.
        self._current_lock = asyncio.Lock()

    # -- read tools -----------------------------------------------------------

    async def get_status(self, *, charger_id: str | None = None) -> dict[str, Any]:
        async def loader() -> dict[str, Any]:
            charger = await self._client.resolve_charger(charger_id)
            state, installation = await asyncio.gather(
                self._client.get_charger_state(field(charger, "Id")),
                self._client.resolve_installation(charger=charger),
            )
            return format_status(charger, state, installation)

        return cast(
            dict[str, Any],
            await self._cache.get_or_load(
                "status", {"charger_id": charger_id}, ttl=TTL_STATUS, loader=loader
            ),
        )

    async def get_installation(self, *, installation_id: str | None = None) -> dict[str, Any]:
        async def loader() -> dict[str, Any]:
            installation = await self._client.resolve_installation(installation_id)
            iid = field(installation, "Id")
            hierarchy = await self._client.get_hierarchy(iid)
            chargers = await self._client.list_chargers()
            return format_installation(installation, hierarchy, chargers)

        return cast(
            dict[str, Any],
            await self._cache.get_or_load(
                "installation",
                {"installation_id": installation_id},
                ttl=TTL_INSTALLATION,
                loader=loader,
            ),
        )

    async def get_charge_history(
        self,
        *,
        charger_id: str | None = None,
        time_range: str = "month",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        first_day, last_day = _parse_date(start_date), _parse_date(end_date)
        if time_range == "custom":
            validate_custom_dates(first_day, last_day)  # fail before any API call

        async def loader() -> dict[str, Any]:
            charger = await self._client.resolve_charger(charger_id)
            installation = await self._client.resolve_installation(charger=charger)
            tz = _tz_of(installation)
            start, end = resolve_range(
                time_range, now=self._now(), tz=tz, start_date=first_day, end_date=last_day
            )
            archived = await self._client.archived_sessions(
                start=start, end=end, charger_id=field(charger, "Id")
            )
            return format_history(
                archived.sessions,
                tz=tz,
                time_range=time_range,
                start=start,
                end=end,
                price_per_kwh=self._cfg.price_per_kwh,
                currency=self._cfg.currency,
                api_truncated=archived.truncated,
            )

        args = {
            "charger_id": charger_id,
            "time_range": time_range,
            "start_date": start_date,
            "end_date": end_date,
        }
        return cast(
            dict[str, Any],
            await self._cache.get_or_load("history", args, ttl=TTL_HISTORY, loader=loader),
        )

    # -- control tools --------------------------------------------------------

    async def _fresh_mode(self, charger_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        charger = await self._client.resolve_charger(charger_id)
        state = await self._client.get_charger_state(field(charger, "Id"))
        sm = StateMap(state)
        mode = summarize_mode(sm, None)
        mode["final_stop_active"] = sm.get_bool(Obs.FINAL_STOP_ACTIVE)
        return charger, mode

    async def _run_command(self, spec: _CommandSpec, charger_id: str | None) -> dict[str, Any]:
        charger, mode = await self._fresh_mode(charger_id)
        cid = field(charger, "Id")
        key = _state_key(mode)
        if key != spec.allowed_state:
            reason = spec.refusals.get(key, _UNKNOWN_STATE)
            raise ZaptecGuardError(
                f"cannot {spec.name}: {reason}", {"operating_mode": mode, "charger_id": cid}
            )
        await self._client.send_command(cid, spec.command_id)
        self._cache.invalidate("status")
        return {
            "ok": True,
            "command": spec.name,
            "charger": {"id": cid, "name": field(charger, "Name")},
            "previous_state": mode,
            "note": spec.note,
        }

    async def pause_charging(self, *, charger_id: str | None = None) -> dict[str, Any]:
        return await self._run_command(_PAUSE, charger_id)

    async def resume_charging(self, *, charger_id: str | None = None) -> dict[str, Any]:
        return await self._run_command(_RESUME, charger_id)

    async def set_available_current(
        self,
        amps: float | None,
        *,
        installation_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        if amps is not None:
            checked = _finite_number(amps)
            if checked is None:
                raise ZaptecGuardError(
                    f"amps must be a finite number or null, got {amps!r}", {"amps": repr(amps)}
                )
            if checked < 0:
                raise ZaptecGuardError("amps must be >= 0", {"amps": checked})
            amps = checked
        installation = await self._client.resolve_installation(installation_id)
        iid = field(installation, "Id")
        max_current = field(installation, "MaxCurrent")
        previous = field(installation, "AvailableCurrent")
        if amps is not None:
            self._check_upper_bound(amps, max_current)
        async with self._current_lock:
            self._check_rate_guard(force)
            await self._client.update_installation(iid, {"availableCurrent": amps})
            self._last_current_update = self._clock()
        self._cache.invalidate("status")
        self._cache.invalidate("installation")
        self._client.invalidate_lists()
        refreshed = await self._client.get_installation(iid)
        return {
            "ok": True,
            "installation": {"id": iid, "name": field(installation, "Name")},
            "previous_available_current_a": previous,
            "requested_available_current_a": amps,
            "new_available_current_a": field(refreshed, "AvailableCurrent"),
            "max_current_a": max_current,
            "note": (
                "Vehicles adapt within about 5 seconds. null means the installation reverted "
                "to its maximum. Avoid changing this more than once every 15 minutes."
            ),
        }

    @staticmethod
    def _check_upper_bound(amps: float, max_current: Any) -> None:
        limit = _finite_number(max_current)
        if limit is None:
            raise ZaptecGuardError(
                "the installation reports no usable MaxCurrent, so the requested current "
                "cannot be checked against the main fuse; refusing to change it. Pass null "
                "to reset to the installation maximum instead.",
                {"max_current_a": max_current},
            )
        if amps > limit:
            raise ZaptecGuardError(
                f"amps {amps} exceeds the installation maximum of {max_current} A",
                {"max_current_a": max_current},
            )

    def _check_rate_guard(self, force: bool) -> None:
        interval = self._cfg.min_current_update_interval
        if interval <= 0 or force or self._last_current_update is None:
            return
        elapsed = self._clock() - self._last_current_update
        if elapsed < interval:
            wait = round(interval - elapsed)
            raise ZaptecGuardError(
                f"available current was changed {round(elapsed)} s ago; Zaptec recommends "
                f"at most one change every {round(interval)} s. Wait {wait} s or pass "
                "force=true.",
                {"seconds_until_allowed": wait, "min_interval_seconds": interval},
            )
