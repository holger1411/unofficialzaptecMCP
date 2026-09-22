"""Tool implementations: caching, guards and orchestration over ZaptecClient."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any, cast
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
from .zaptec.observations import Obs, StateMap, field
from .zaptec.timeranges import resolve_range

log = logging.getLogger(__name__)

TTL_STATUS = 15.0
TTL_INSTALLATION = 300.0
TTL_HISTORY = 300.0

MODE_DISCONNECTED = 1
MODE_REQUESTING = 2
MODE_CHARGING = 3
MODE_FINISHED = 5


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
    return datetime.now(timezone.utc)


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

    # -- read tools -----------------------------------------------------------

    async def get_status(self, *, charger_id: str | None = None) -> dict[str, Any]:
        async def loader() -> dict[str, Any]:
            charger = await self._client.resolve_charger(charger_id)
            state = await self._client.get_charger_state(field(charger, "Id"))
            installation = await self._client.resolve_installation(charger=charger)
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
        async def loader() -> dict[str, Any]:
            charger = await self._client.resolve_charger(charger_id)
            installation = await self._client.resolve_installation(charger=charger)
            tz = _tz_of(installation)
            start, end = resolve_range(
                time_range,
                now=self._now(),
                tz=tz,
                start_date=_parse_date(start_date),
                end_date=_parse_date(end_date),
            )
            sessions = await self._client.archived_sessions(
                start=start, end=end, charger_id=field(charger, "Id")
            )
            return format_history(
                sessions,
                tz=tz,
                time_range=time_range,
                start=start,
                end=end,
                price_per_kwh=self._cfg.price_per_kwh,
                currency=self._cfg.currency,
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

    async def _fresh_mode(
        self, charger_id: str | None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        charger = await self._client.resolve_charger(charger_id)
        state = await self._client.get_charger_state(field(charger, "Id"))
        sm = StateMap(state)
        mode = summarize_mode(sm, None)
        mode["final_stop_active"] = sm.get_bool(Obs.FINAL_STOP_ACTIVE)
        return charger, mode

    async def pause_charging(self, *, charger_id: str | None = None) -> dict[str, Any]:
        charger, mode = await self._fresh_mode(charger_id)
        code = mode["code"]
        if code != MODE_CHARGING:
            if code == MODE_FINISHED and mode["final_stop_active"]:
                reason = "charging is already paused"
            elif code == MODE_FINISHED:
                reason = (
                    "the vehicle is connected but not charging "
                    "(finished or stopped by the vehicle)"
                )
            elif code == MODE_DISCONNECTED:
                reason = "no vehicle is connected"
            elif code == MODE_REQUESTING:
                reason = (
                    "the charger is waiting for authorization or for the vehicle to request power"
                )
            else:
                reason = "the charger state is unknown"
            raise ZaptecGuardError(
                f"cannot pause: {reason}",
                {"operating_mode": mode, "charger_id": field(charger, "Id")},
            )
        await self._client.send_command(field(charger, "Id"), CMD_PAUSE)
        self._cache.invalidate("status")
        return {
            "ok": True,
            "command": "pause",
            "charger": {"id": field(charger, "Id"), "name": field(charger, "Name")},
            "previous_state": mode,
            "note": (
                "Pause requested. Within a few seconds the charger reports mode "
                "connected_finished with final_stop_active=true."
            ),
        }

    async def resume_charging(self, *, charger_id: str | None = None) -> dict[str, Any]:
        charger, mode = await self._fresh_mode(charger_id)
        code = mode["code"]
        if not (code == MODE_FINISHED and mode["final_stop_active"]):
            if code == MODE_CHARGING:
                reason = "the charger is already charging"
            elif code == MODE_DISCONNECTED:
                reason = "no vehicle is connected"
            elif code == MODE_REQUESTING:
                reason = (
                    "the charger is waiting for authorization or for the vehicle; "
                    "resume only works for a paused session"
                )
            elif code == MODE_FINISHED:
                reason = (
                    "the session is not paused by the charger; the vehicle stopped charging "
                    "itself (full battery, schedule or vehicle app)"
                )
            else:
                reason = "the charger state is unknown"
            raise ZaptecGuardError(
                f"cannot resume: {reason}",
                {"operating_mode": mode, "charger_id": field(charger, "Id")},
            )
        await self._client.send_command(field(charger, "Id"), CMD_RESUME)
        self._cache.invalidate("status")
        return {
            "ok": True,
            "command": "resume",
            "charger": {"id": field(charger, "Id"), "name": field(charger, "Name")},
            "previous_state": mode,
            "note": "Resume requested. Charging restarts within seconds if the vehicle accepts power.",
        }

    async def set_available_current(
        self,
        amps: float | None,
        *,
        installation_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        installation = await self._client.resolve_installation(installation_id)
        iid = field(installation, "Id")
        max_current = field(installation, "MaxCurrent")
        previous = field(installation, "AvailableCurrent")
        if amps is not None:
            amps = float(amps)
            if amps < 0:
                raise ZaptecGuardError("amps must be >= 0", {"max_current_a": max_current})
            if isinstance(max_current, (int, float)) and amps > float(max_current):
                raise ZaptecGuardError(
                    f"amps {amps} exceeds the installation maximum of {max_current} A",
                    {"max_current_a": max_current},
                )
        interval = self._cfg.min_current_update_interval
        if interval > 0 and not force and self._last_current_update is not None:
            elapsed = self._clock() - self._last_current_update
            if elapsed < interval:
                wait = round(interval - elapsed)
                raise ZaptecGuardError(
                    f"available current was changed {round(elapsed)} s ago; Zaptec recommends "
                    f"at most one change every {round(interval)} s. Wait {wait} s or pass "
                    "force=true.",
                    {"seconds_until_allowed": wait, "min_interval_seconds": interval},
                )
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
