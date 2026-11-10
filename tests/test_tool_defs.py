from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest
from jsonschema import Draft202012Validator
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS

from tests.conftest import load_fixture
from tests.test_server import build, fixture_api
from tests.test_server_control import cid, iid, state_with
from zaptec_mcp_server.__main__ import build_server
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.tool_defs import call_tool, dispatch, tool_definitions
from zaptec_mcp_server.utils.errors import ZaptecGuardError

WRITE_TOOLS = ("zaptec_pause_charging", "zaptec_resume_charging", "zaptec_set_available_current")


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


def defs() -> dict[str, Any]:
    return {t.name: t for t in tool_definitions()}


def test_tool_definitions_names_and_schemas() -> None:
    d = defs()
    assert set(d) == {
        "zaptec_get_status",
        "zaptec_get_installation",
        "zaptec_get_charge_history",
        "zaptec_pause_charging",
        "zaptec_resume_charging",
        "zaptec_set_available_current",
    }
    assert d["zaptec_set_available_current"].input_schema["required"] == ["amps"]
    history = d["zaptec_get_charge_history"].input_schema["properties"]["time_range"]
    assert "custom" in history["enum"]
    for t in d.values():
        assert t.input_schema["additionalProperties"] is False
        assert t.title
        assert t.output_schema is not None
        Draft202012Validator.check_schema(t.input_schema)
        Draft202012Validator.check_schema(t.output_schema)
    for name in WRITE_TOOLS:
        assert d[name].description.startswith("CHANGES STATE")


def test_tool_order_is_deterministic() -> None:
    assert [t.name for t in tool_definitions()] == [t.name for t in tool_definitions()]


def test_annotations() -> None:
    d = defs()
    for name, t in d.items():
        assert t.annotations is not None
        assert t.annotations.open_world_hint is True
        assert t.annotations.read_only_hint is (name not in WRITE_TOOLS)
    assert d["zaptec_pause_charging"].annotations.destructive_hint is False
    assert d["zaptec_resume_charging"].annotations.destructive_hint is False
    assert d["zaptec_set_available_current"].annotations.destructive_hint is True


def test_history_input_schema_requires_dates_for_custom() -> None:
    v = Draft202012Validator(defs()["zaptec_get_charge_history"].input_schema)
    assert v.is_valid({"time_range": "week"})
    assert not v.is_valid({"time_range": "custom"})
    assert v.is_valid(
        {"time_range": "custom", "start_date": "2026-01-01", "end_date": "2026-01-31"}
    )


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
    assert s.calls[5] == (
        "set_available_current",
        {"amps": 10, "installation_id": None, "force": False},
    )
    assert s.calls[6][1]["amps"] is None


async def test_call_tool_success_has_text_and_structured_content() -> None:
    _, tools = stub()
    result = await call_tool(tools, "zaptec_get_status", {})
    assert result.is_error is False
    assert result.structured_content == {"ok": 1}
    assert json.loads(result.content[0].text) == {"ok": 1}  # type: ignore[union-attr]


async def test_call_tool_errors_are_tool_execution_errors() -> None:
    _, tools = stub()
    guard = await call_tool(tools, "zaptec_set_available_current", {"amps": 1, "force": True})
    assert guard.is_error is True
    assert guard.structured_content is None
    payload = json.loads(guard.content[0].text)  # type: ignore[union-attr]
    assert payload["error_type"] == "ZaptecGuardError"
    assert payload["seconds_until_allowed"] == 5
    bad = await call_tool(tools, "zaptec_get_charge_history", {"time_range": "bogus"})
    assert bad.is_error is True
    bad_payload = json.loads(bad.content[0].text)  # type: ignore[union-attr]
    assert bad_payload["error_type"] == "InputValidationError"


@pytest.mark.parametrize(
    "args",
    [
        {"time_range": "custom"},
        {"time_range": "custom", "start_date": "22.09.2026", "end_date": "2026-09-30"},
        {"charger_id": "c", "extra": 1},
    ],
)
async def test_invalid_arguments_never_reach_the_api(args: dict[str, Any]) -> None:
    s, tools = stub()
    result = await call_tool(tools, "zaptec_get_charge_history", args)
    assert result.is_error is True
    assert s.calls == []


async def test_invalid_amps_rejected_before_dispatch() -> None:
    s, tools = stub()
    for args in ({}, {"amps": -1}, {"amps": "ten"}):
        assert (await call_tool(tools, "zaptec_set_available_current", args)).is_error is True
    assert s.calls == []


async def test_unknown_tool_is_a_protocol_error() -> None:
    _, tools = stub()
    with pytest.raises(MCPError) as info:
        await call_tool(tools, "zaptec_nope", {})
    assert info.value.error.code == INVALID_PARAMS


def test_build_server_metadata() -> None:
    _, tools = stub()
    server = build_server(tools)
    assert server.name == "unofficial-zaptec-mcp"
    assert server.version


# -- real outputs conform to the declared outputSchema ------------------------


async def _structured(tools: ZaptecTools, name: str, args: dict[str, Any]) -> Any:
    result = await call_tool(tools, name, args)
    assert result.is_error is False, result.content
    Draft202012Validator(defs()[name].output_schema).validate(result.structured_content)
    return result.structured_content


async def test_read_outputs_match_schema() -> None:
    tools = build(fixture_api(), {"ZAPTEC_PRICE_PER_KWH": "0.35"})
    await _structured(tools, "zaptec_get_status", {})
    await _structured(tools, "zaptec_get_installation", {})
    out = await _structured(tools, "zaptec_get_charge_history", {"time_range": "year"})
    assert "cost" in out["summary"]
    await _structured(build(fixture_api()), "zaptec_get_charge_history", {})


async def test_command_outputs_match_schema() -> None:
    api = fixture_api(
        state_with(3), {("POST", f"/api/chargers/{cid()}/sendCommand/506"): [httpx.Response(200)]}
    )
    await _structured(build(api), "zaptec_pause_charging", {})
    api = fixture_api(
        state_with(5, 1),
        {("POST", f"/api/chargers/{cid()}/sendCommand/507"): [httpx.Response(200)]},
    )
    await _structured(build(api), "zaptec_resume_charging", {})
    api = fixture_api(
        None,
        {
            ("POST", f"/api/installation/{iid()}/update"): [httpx.Response(200)],
            ("GET", f"/api/installation/{iid()}"): [
                httpx.Response(200, json=load_fixture("installation")),
            ],
        },
    )
    await _structured(build(api), "zaptec_set_available_current", {"amps": None})


# -- registry, id schemas, descriptions --------------------------------------------

CHARGER = "00000001-0000-4000-8000-000000000001"
INSTALLATION = "00000003-0000-4000-8000-000000000003"


async def test_every_listed_tool_dispatches() -> None:
    s, tools = stub()
    for t in tool_definitions():
        await dispatch(tools, t.name, {"amps": 1} if t.name.endswith("current") else {})
    assert len(s.calls) == len(tool_definitions())


async def test_dispatch_unknown_tool_raises() -> None:
    _, tools = stub()
    with pytest.raises(MCPError):
        await dispatch(tools, "zaptec_nope", {})


def test_tool_definitions_returns_independent_copies() -> None:
    first = tool_definitions()
    first[0].description = "mutated"
    assert tool_definitions()[0].description != "mutated"


@pytest.mark.parametrize(
    ("name", "key", "value"),
    [
        ("zaptec_get_status", "charger_id", CHARGER),
        ("zaptec_get_status", "charger_id", CHARGER.upper()),
        ("zaptec_pause_charging", "charger_id", CHARGER),
        ("zaptec_resume_charging", "charger_id", CHARGER),
        ("zaptec_get_charge_history", "charger_id", CHARGER),
        ("zaptec_get_installation", "installation_id", INSTALLATION),
    ],
)
async def test_uuid_ids_are_accepted(name: str, key: str, value: str) -> None:
    s, tools = stub()
    result = await call_tool(tools, name, {key: value})
    assert result.is_error is False
    assert s.calls[0][1][key] == value


@pytest.mark.parametrize(
    "bad",
    [
        "c",
        "../installation/x",
        "00000001-0000-4000-8000-00000000000",
        "00000001-0000-4000-8000-0000000000011",
        "000000010000400080000000000000001",
        "{00000001-0000-4000-8000-000000000001}",
        "urn:uuid:00000001-0000-4000-8000-000000000001",
        "00000001-0000-4000-8000-00000000000g",
        "00000001-0000-4000-8000-000000000001\n",
        "",
    ],
)
@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("zaptec_get_status", "charger_id"),
        ("zaptec_pause_charging", "charger_id"),
        ("zaptec_resume_charging", "charger_id"),
        ("zaptec_get_charge_history", "charger_id"),
        ("zaptec_get_installation", "installation_id"),
        ("zaptec_set_available_current", "installation_id"),
    ],
)
async def test_malformed_ids_are_input_validation_errors(name: str, key: str, bad: str) -> None:
    s, tools = stub()
    args: dict[str, Any] = {key: bad}
    if name == "zaptec_set_available_current":
        args["amps"] = 10
    result = await call_tool(tools, name, args)
    assert result.is_error is True
    payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert payload["error_type"] == "InputValidationError"
    assert s.calls == []


def test_id_schemas_declare_uuid() -> None:
    for t in tool_definitions():
        for key in ("charger_id", "installation_id"):
            prop = t.input_schema["properties"].get(key)
            if prop is not None:
                assert prop["format"] == "uuid"
                assert prop["pattern"].startswith("^")


def test_zero_amps_is_explained() -> None:
    t = defs()["zaptec_set_available_current"]
    assert "0 A stops charging" in t.description
    assert "0 stops charging" in t.input_schema["properties"]["amps"]["description"]


def test_history_output_schema_declares_truncation_reasons() -> None:
    schema = defs()["zaptec_get_charge_history"].output_schema
    assert schema is not None
    assert schema["properties"]["truncated"]["type"] == "boolean"
    assert "truncated_by" in schema["required"]
    v = Draft202012Validator(schema["properties"]["truncated_by"])
    assert v.is_valid(["display_limit", "api_page_limit"])
    assert not v.is_valid(["other"])


async def test_history_custom_range_errors_are_tool_errors() -> None:
    tools = build(fixture_api())
    result = await call_tool(
        tools,
        "zaptec_get_charge_history",
        {"time_range": "custom", "start_date": "2026-09-10", "end_date": "2026-09-01"},
    )
    assert result.is_error is True
    payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert payload["error_type"] == "ValueError"
    assert "before start_date" in payload["message"]


async def test_truncated_history_output_matches_schema() -> None:
    sessions = load_fixture("sessions_archived")
    many = [
        {
            **sessions["sessions"][0],
            "Id": f"s{i}",
            "StartDateTime": f"2026-09-0{1 + i % 9}T10:00:00",
        }
        for i in range(501)
    ]
    api = fixture_api(
        None,
        {
            ("GET", "/api/sessions/archived"): [
                httpx.Response(200, json={**sessions, "sessions": many})
            ]
        },
    )
    out = await _structured(build(api), "zaptec_get_charge_history", {})
    assert out["truncated"] is True
    assert out["truncated_by"] == ["display_limit"]
    assert len(out["sessions"]) == 500
