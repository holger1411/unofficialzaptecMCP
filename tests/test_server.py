from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from tests.conftest import load_fixture
from tests.test_client import FakeApi
from zaptec_mcp_server.cache.manager import CacheManager
from zaptec_mcp_server.config import ServerConfig
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.zaptec.client import ZaptecClient

NOW = datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)


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
