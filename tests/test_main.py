from __future__ import annotations

import json
from typing import Any, cast

import pytest

from zaptec_mcp_server.__main__ import dispatch, tool_definitions
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.utils.errors import ZaptecGuardError


class StubTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_status(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get_status", kw))
        return {"ok": 1}

    async def get_installation(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get_installation", kw))
        return {}

    async def get_charge_history(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get_charge_history", kw))
        if kw.get("time_range") == "custom":
            raise ValueError("custom range requires start_date and end_date")
        return {}

    async def pause_charging(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("pause_charging", kw))
        return {}

    async def resume_charging(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("resume_charging", kw))
        return {}

    async def set_available_current(self, amps: float | None, **kw: Any) -> dict[str, Any]:
        self.calls.append(("set_available_current", {"amps": amps, **kw}))
        if kw.get("force"):
            raise ZaptecGuardError("nope", {"seconds_until_allowed": 5})
        return {}


def stub() -> tuple[StubTools, ZaptecTools]:
    s = StubTools()
    return s, cast(ZaptecTools, s)


def test_tool_definitions_names_and_schemas() -> None:
    defs = {t.name: t for t in tool_definitions()}
    assert set(defs) == {
        "zaptec_get_status",
        "zaptec_get_installation",
        "zaptec_get_charge_history",
        "zaptec_pause_charging",
        "zaptec_resume_charging",
        "zaptec_set_available_current",
    }
    assert defs["zaptec_set_available_current"].inputSchema["required"] == ["amps"]
    history = defs["zaptec_get_charge_history"].inputSchema["properties"]["time_range"]
    assert "custom" in history["enum"]
    for t in defs.values():
        assert t.inputSchema["additionalProperties"] is False
    for name in ("zaptec_pause_charging", "zaptec_resume_charging", "zaptec_set_available_current"):
        assert defs[name].description.startswith("CHANGES STATE")


async def test_dispatch_routes_arguments() -> None:
    s, tools = stub()
    assert await dispatch(tools, "zaptec_get_status", {"charger_id": "c"}) == {"ok": 1}
    await dispatch(tools, "zaptec_get_installation", None)
    await dispatch(tools, "zaptec_get_charge_history", {"time_range": "week"})
    await dispatch(tools, "zaptec_pause_charging", {})
    await dispatch(tools, "zaptec_resume_charging", {"charger_id": "x"})
    await dispatch(tools, "zaptec_set_available_current", {"amps": 10})
    await dispatch(tools, "zaptec_set_available_current", {"amps": None})
    assert s.calls[0] == ("get_status", {"charger_id": "c"})
    assert s.calls[1] == ("get_installation", {"installation_id": None})
    assert s.calls[2] == (
        "get_charge_history",
        {"charger_id": None, "time_range": "week", "start_date": None, "end_date": None},
    )
    assert s.calls[3] == ("pause_charging", {"charger_id": None})
    assert s.calls[4] == ("resume_charging", {"charger_id": "x"})
    assert s.calls[5] == ("set_available_current", {"amps": 10, "installation_id": None, "force": False})
    assert s.calls[6][1]["amps"] is None


async def test_dispatch_unknown_tool_and_error_payloads() -> None:
    _, tools = stub()
    with pytest.raises(RuntimeError) as info:
        await dispatch(tools, "zaptec_nope", {})
    assert json.loads(str(info.value))["error_type"] == "ZaptecError"
    with pytest.raises(RuntimeError) as info2:
        await dispatch(tools, "zaptec_set_available_current", {"amps": 1, "force": True})
    payload = json.loads(str(info2.value))
    assert payload["error_type"] == "ZaptecGuardError"
    assert payload["seconds_until_allowed"] == 5
    with pytest.raises(RuntimeError) as info3:
        await dispatch(tools, "zaptec_get_charge_history", {"time_range": "custom"})
    assert json.loads(str(info3.value))["error_type"] == "ValueError"
