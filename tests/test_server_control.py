from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx
import pytest

from tests.conftest import load_fixture
from tests.test_server import build, fixture_api
from zaptec_mcp_server.cache.manager import CacheManager
from zaptec_mcp_server.config import ServerConfig
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.utils.errors import ZaptecCommandRejectedError, ZaptecGuardError
from zaptec_mcp_server.zaptec.client import ZaptecClient


def state_with(mode: int, final_stop: int = 0) -> list[dict[str, Any]]:
    base = [s for s in load_fixture("charger_state") if s["StateId"] not in (710, 718)]
    base.append({"StateId": 710, "ValueAsString": str(mode), "Timestamp": "2026-09-22T14:40:00"})
    base.append(
        {"StateId": 718, "ValueAsString": str(final_stop), "Timestamp": "2026-09-22T14:40:00"}
    )
    return base


def cid() -> str:
    return str(load_fixture("chargers")["Data"][0]["Id"])


def iid() -> str:
    return str(load_fixture("chargers")["Data"][0]["InstallationId"])


async def test_pause_when_charging() -> None:
    api = fixture_api(
        state_with(3), {("POST", f"/api/chargers/{cid()}/sendCommand/506"): [httpx.Response(200)]}
    )
    tools = build(api)
    await tools.get_status()  # warm cache; pause must invalidate it
    out = await tools.pause_charging()
    assert out["ok"] is True
    assert out["command"] == "pause"
    assert out["previous_state"]["name"] == "connected_charging"
    assert any(c.url.path.endswith("/sendCommand/506") for c in api.calls)
    await tools.get_status()
    # status, pause precondition check, status again after invalidation
    assert len([c for c in api.calls if c.url.path.endswith("/state")]) == 3


async def test_pause_rejected_when_not_charging() -> None:
    tools = build(fixture_api(state_with(5, 1)))
    with pytest.raises(ZaptecGuardError) as info:
        await tools.pause_charging()
    assert info.value.payload["operating_mode"]["name"] == "connected_finished"
    assert "already paused" in str(info.value)


async def test_resume_when_paused() -> None:
    api = fixture_api(
        state_with(5, 1),
        {("POST", f"/api/chargers/{cid()}/sendCommand/507"): [httpx.Response(200)]},
    )
    out = await build(api).resume_charging()
    assert out["command"] == "resume"


@pytest.mark.parametrize(
    ("mode", "final_stop", "phrase"),
    [(3, 0, "already charging"), (1, 0, "no vehicle"), (2, 0, "waiting"), (5, 0, "vehicle")],
)
async def test_resume_guard_messages(mode: int, final_stop: int, phrase: str) -> None:
    tools = build(fixture_api(state_with(mode, final_stop)))
    with pytest.raises(ZaptecGuardError) as info:
        await tools.resume_charging()
    assert phrase in str(info.value)


async def test_cloud_rejection_propagates() -> None:
    api = fixture_api(
        state_with(5, 1),
        {
            ("POST", f"/api/chargers/{cid()}/sendCommand/507"): [
                httpx.Response(500, json={"Code": 528, "Details": "nope"})
            ]
        },
    )
    with pytest.raises(ZaptecCommandRejectedError):
        await build(api).resume_charging()


def _updated_installation(amps: float | None) -> dict[str, Any]:
    inst = dict(load_fixture("installation"))
    inst["AvailableCurrent"] = amps
    return inst


async def test_set_available_current_happy_path_and_guard() -> None:
    clock = [1000.0]
    api = fixture_api(
        None,
        {
            ("POST", f"/api/installation/{iid()}/update"): [httpx.Response(200)],
            ("GET", f"/api/installation/{iid()}"): [
                httpx.Response(200, json=load_fixture("installation")),
                httpx.Response(200, json=_updated_installation(10.0)),
            ],
        },
    )
    tools = build(api, clock=clock)
    out = await tools.set_available_current(10)
    assert out["ok"] is True
    assert out["previous_available_current_a"] is None
    assert out["new_available_current_a"] == 10.0
    assert out["max_current_a"] == 32.0
    post = next(c for c in api.calls if c.method == "POST" and c.url.path.endswith("/update"))
    assert json.loads(post.content) == {"availableCurrent": 10.0}
    clock[0] += 100
    with pytest.raises(ZaptecGuardError) as info:
        await tools.set_available_current(12)
    assert info.value.payload["seconds_until_allowed"] == 800
    clock[0] += 900
    await tools.set_available_current(12)


async def test_set_available_current_force_and_reset() -> None:
    clock = [1000.0]
    api = fixture_api(None, {("POST", f"/api/installation/{iid()}/update"): [httpx.Response(200)]})
    tools = build(api, clock=clock)
    await tools.set_available_current(16)
    await tools.set_available_current(None, force=True)
    posts = [c for c in api.calls if c.method == "POST" and c.url.path.endswith("/update")]
    assert json.loads(posts[1].content) == {"availableCurrent": None}


async def test_set_available_current_validation() -> None:
    tools = build(fixture_api())
    with pytest.raises(ZaptecGuardError):
        await tools.set_available_current(40)
    with pytest.raises(ZaptecGuardError):
        await tools.set_available_current(-1)


async def test_guard_disabled_by_config() -> None:
    api = fixture_api(None, {("POST", f"/api/installation/{iid()}/update"): [httpx.Response(200)]})
    tools = build(api, {"ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL": "0"})
    await tools.set_available_current(8)
    await tools.set_available_current(9)


# -- set_available_current hardening --------------------------------------------


class CurrentStubClient:
    """Minimal ZaptecClient stand-in for set_available_current."""

    def __init__(self, installation: dict[str, Any]) -> None:
        self.installation = installation
        self.updates: list[dict[str, Any]] = []

    async def resolve_installation(
        self, installation_id: str | None = None, **_: Any
    ) -> dict[str, Any]:
        return self.installation

    async def update_installation(self, installation_id: str, body: dict[str, Any]) -> None:
        await asyncio.sleep(0.01)
        self.updates.append(body)

    async def get_installation(self, installation_id: str) -> dict[str, Any]:
        return self.installation

    def invalidate_lists(self) -> None:
        pass


def stub_tools(installation: dict[str, Any]) -> tuple[CurrentStubClient, ZaptecTools]:
    client = CurrentStubClient(installation)
    cfg = ServerConfig.from_env({"ZAPTEC_USERNAME": "u@example.com", "ZAPTEC_PASSWORD": "pw123456"})
    tools = ZaptecTools(
        client=cast(ZaptecClient, client), cache=CacheManager(), cfg=cfg, clock=lambda: 1000.0
    )
    return client, tools


async def test_concurrent_current_updates_are_serialized_by_the_guard() -> None:
    client, tools = stub_tools(dict(load_fixture("installation")))
    results = await asyncio.gather(
        tools.set_available_current(10),
        tools.set_available_current(12),
        return_exceptions=True,
    )
    assert len(client.updates) == 1
    assert sum(isinstance(r, ZaptecGuardError) for r in results) == 1


@pytest.mark.parametrize("max_current", [None, "32", float("nan"), True])
async def test_refuses_amps_without_usable_max_current(max_current: Any) -> None:
    inst = dict(load_fixture("installation"))
    inst["MaxCurrent"] = max_current
    client, tools = stub_tools(inst)
    with pytest.raises(ZaptecGuardError, match="MaxCurrent"):
        await tools.set_available_current(500)
    with pytest.raises(ZaptecGuardError, match="MaxCurrent"):
        await tools.set_available_current(6)
    assert client.updates == []


async def test_reset_allowed_without_max_current() -> None:
    inst = dict(load_fixture("installation"))
    del inst["MaxCurrent"]
    client, tools = stub_tools(inst)
    await tools.set_available_current(None)
    assert client.updates == [{"availableCurrent": None}]


@pytest.mark.parametrize("amps", [float("nan"), float("inf"), float("-inf"), True, False, "10"])
async def test_rejects_non_finite_and_non_numeric_amps(amps: Any) -> None:
    client, tools = stub_tools(dict(load_fixture("installation")))
    with pytest.raises(ZaptecGuardError, match="finite number"):
        await tools.set_available_current(amps)
    assert client.updates == []


async def test_zero_amps_is_accepted() -> None:
    client, tools = stub_tools(dict(load_fixture("installation")))
    out = await tools.set_available_current(0)
    assert client.updates == [{"availableCurrent": 0.0}]
    assert out["requested_available_current_a"] == 0.0


@pytest.mark.parametrize(("mode", "final_stop"), [(1, 0), (2, 0), (5, 0), (0, 0), (4, 0)])
async def test_pause_guard_messages(mode: int, final_stop: int) -> None:
    phrases = {
        1: "no vehicle",
        2: "waiting for authorization",
        5: "not charging",
        0: "unknown",
        4: "unknown",
    }
    tools = build(fixture_api(state_with(mode, final_stop)))
    with pytest.raises(ZaptecGuardError) as info:
        await tools.pause_charging()
    assert str(info.value).startswith("cannot pause: ")
    assert phrases[mode] in str(info.value)
    assert info.value.payload["charger_id"] == cid()


async def test_resume_guard_unknown_state() -> None:
    tools = build(fixture_api(state_with(0)))
    with pytest.raises(ZaptecGuardError, match="cannot resume: the charger state is unknown"):
        await tools.resume_charging()
