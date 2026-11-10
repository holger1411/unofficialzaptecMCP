from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from tests.conftest import load_fixture
from tests.test_client import FakeApi
from zaptec_mcp_server.cache.manager import CacheManager
from zaptec_mcp_server.config import ServerConfig
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.zaptec.client import ArchivedSessions, ZaptecClient

NOW = datetime(2026, 9, 22, 14, 30, tzinfo=UTC)


def build(
    api: FakeApi, env: dict[str, str] | None = None, clock: list[float] | None = None
) -> ZaptecTools:
    cfg = ServerConfig.from_env(
        {"ZAPTEC_USERNAME": "u@example.com", "ZAPTEC_PASSWORD": "pw123456", **(env or {})}
    )
    tick = clock or [1000.0]

    async def no_sleep(_: float) -> None:
        pass

    client = ZaptecClient(cfg, transport=api.transport(), sleep=no_sleep, clock=lambda: tick[0])
    return ZaptecTools(
        client=client, cache=CacheManager(), cfg=cfg, clock=lambda: tick[0], now=lambda: NOW
    )


def fixture_api(
    state: list[dict[str, Any]] | None = None,
    extra: dict[tuple[str, str], list[httpx.Response]] | None = None,
) -> FakeApi:
    chargers = load_fixture("chargers")
    cid = chargers["Data"][0]["Id"]
    iid = chargers["Data"][0]["InstallationId"]
    script: dict[tuple[str, str], list[httpx.Response]] = {
        ("GET", "/api/chargers"): [httpx.Response(200, json=chargers)],
        ("GET", f"/api/chargers/{cid}/state"): [
            httpx.Response(200, json=state if state is not None else load_fixture("charger_state"))
        ],
        ("GET", f"/api/installation/{iid}"): [
            httpx.Response(200, json=load_fixture("installation"))
        ],
        ("GET", f"/api/installation/{iid}/hierarchy"): [
            httpx.Response(200, json=load_fixture("hierarchy"))
        ],
        ("GET", "/api/sessions/archived"): [
            httpx.Response(200, json=load_fixture("sessions_archived"))
        ],
    }
    script.update(extra or {})
    return FakeApi(script)


async def test_get_status_and_cache() -> None:
    api = fixture_api()
    tools = build(api)
    out = await tools.get_status()
    assert out["operating_mode"]["name"] == "connected_charging"
    await tools.get_status()
    assert len([c for c in api.calls if c.url.path.endswith("/state")]) == 1


async def test_get_installation() -> None:
    tools = build(fixture_api())
    out = await tools.get_installation()
    assert out["timezone"] == "Europe/Berlin"
    assert out["circuits"][0]["chargers"][0]["name"] == "Garage"


async def test_get_charge_history_uses_installation_timezone_and_price() -> None:
    api = fixture_api()
    tools = build(api, {"ZAPTEC_PRICE_PER_KWH": "0.30"})
    out = await tools.get_charge_history(time_range="month")
    assert out["timezone"] == "Europe/Berlin"
    assert out["start"] == "2026-09-01T00:00:00+02:00"
    assert out["summary"]["cost"] == 8.27
    call = next(c for c in api.calls if c.url.path == "/api/sessions/archived")
    assert call.url.params["From"] == "2026-08-31T22:00:00Z"


async def test_get_charge_history_custom_requires_dates() -> None:
    tools = build(fixture_api())
    with pytest.raises(ValueError):
        await tools.get_charge_history(time_range="custom")
    out = await tools.get_charge_history(
        time_range="custom", start_date="2026-09-01", end_date="2026-09-21"
    )
    assert out["end"] == "2026-09-22T00:00:00+02:00"


async def test_unknown_timezone_falls_back_to_utc() -> None:
    inst = dict(load_fixture("installation"))
    inst["TimeZoneIanaName"] = "Mars/Olympus"
    iid = inst["Id"]
    api = fixture_api(None, {("GET", f"/api/installation/{iid}"): [httpx.Response(200, json=inst)]})
    out = await build(api).get_charge_history(time_range="today")
    assert out["timezone"] == "UTC"


# -- stub-client tests ------------------------------------------------------------


class ReadStubClient:
    """ZaptecClient stand-in that records how many calls overlap."""

    def __init__(self, sessions: ArchivedSessions | None = None) -> None:
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []
        self.sessions = sessions or ArchivedSessions([], False)
        self.charger = load_fixture("chargers")["Data"][0]

    async def _io(self, name: str) -> None:
        self.calls.append(name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1

    async def resolve_charger(self, charger_id: str | None = None) -> dict[str, Any]:
        await self._io("resolve_charger")
        return dict(self.charger)

    async def get_charger_state(self, charger_id: str) -> list[dict[str, Any]]:
        await self._io("get_charger_state")
        return list(load_fixture("charger_state"))

    async def resolve_installation(
        self, installation_id: str | None = None, *, charger: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        await self._io("resolve_installation")
        return dict(load_fixture("installation"))

    async def archived_sessions(self, **_: Any) -> ArchivedSessions:
        await self._io("archived_sessions")
        return self.sessions


def build_stub(client: ReadStubClient) -> ZaptecTools:
    cfg = ServerConfig.from_env({"ZAPTEC_USERNAME": "u@example.com", "ZAPTEC_PASSWORD": "pw123456"})
    return ZaptecTools(
        client=cast(ZaptecClient, client), cache=CacheManager(), cfg=cfg, now=lambda: NOW
    )


async def test_get_status_fetches_state_and_installation_concurrently() -> None:
    client = ReadStubClient()
    out = await build_stub(client).get_status()
    assert out["operating_mode"]["name"] == "connected_charging"
    assert client.max_active == 2


async def test_parallel_get_status_calls_load_once() -> None:
    client = ReadStubClient()
    tools = build_stub(client)
    first, second = await asyncio.gather(tools.get_status(), tools.get_status())
    assert first == second
    assert client.calls.count("get_charger_state") == 1


async def test_history_reports_client_pagination_cap() -> None:
    sessions = load_fixture("sessions_archived")["sessions"]
    client = ReadStubClient(ArchivedSessions(sessions, True))
    out = await build_stub(client).get_charge_history(time_range="month")
    assert out["truncated"] is True
    assert out["truncated_by"] == ["api_page_limit"]
    assert out["summary"]["session_count"] == len(out["sessions"])


async def test_history_not_truncated() -> None:
    sessions = load_fixture("sessions_archived")["sessions"]
    out = await build_stub(ReadStubClient(ArchivedSessions(sessions, False))).get_charge_history()
    assert out["truncated"] is False
    assert out["truncated_by"] == []


@pytest.mark.parametrize(
    ("start", "end", "phrase"),
    [
        ("2026-09-10", "2026-09-01", "before start_date"),
        ("2025-01-01", "2026-09-01", "maximum is 366 days"),
    ],
)
async def test_custom_range_rejected_before_any_api_call(start: str, end: str, phrase: str) -> None:
    client = ReadStubClient()
    with pytest.raises(ValueError, match=phrase):
        await build_stub(client).get_charge_history(
            time_range="custom", start_date=start, end_date=end
        )
    assert client.calls == []
