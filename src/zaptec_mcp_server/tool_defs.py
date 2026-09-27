"""MCP tool definitions (input/output schemas, annotations) and dispatch to ZaptecTools."""

from __future__ import annotations

import json
import logging
from typing import Any

from jsonschema import Draft202012Validator
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult, TextContent, Tool, ToolAnnotations

from .server import ZaptecTools
from .utils.errors import ZaptecError

log = logging.getLogger("zaptec_mcp_server")

# -- shared schema fragments --------------------------------------------------

_CHARGER_ID = {
    "type": "string",
    "description": "Optional charger id. Defaults to ZAPTEC_DEFAULT_CHARGER_ID or the only charger.",
}
_INSTALLATION_ID = {
    "type": "string",
    "description": "Optional installation id. Defaults to the installation of the default charger.",
}

# Values passed through from the Zaptec API carry no type constraint: the API is
# not under our control and outputSchema validation must not break on it.
_API: dict[str, Any] = {}
_NUM = {"type": ["number", "null"]}
_INT = {"type": ["integer", "null"]}
_STR = {"type": ["string", "null"]}
_BOOL = {"type": ["boolean", "null"]}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
_PHASES = {
    "type": "object",
    "properties": {"l1": _NUM, "l2": _NUM, "l3": _NUM},
    "required": ["l1", "l2", "l3"],
}
_API_PHASES = {
    "type": "object",
    "properties": {"l1": _API, "l2": _API, "l3": _API},
    "required": ["l1", "l2", "l3"],
}
_MODE: dict[str, Any] = {
    "type": "object",
    "properties": {"code": _INT, "name": {"type": "string"}, "hint": {"type": "string"}},
    "required": ["code", "name", "hint"],
}
_MODE_WITH_STOP = {
    "type": "object",
    "properties": {**_MODE["properties"], "final_stop_active": _BOOL},
    "required": ["code", "name", "hint", "final_stop_active"],
}
_REF = {
    "type": "object",
    "properties": {"id": _API, "name": _API},
    "required": ["id", "name"],
}

# -- output schemas -----------------------------------------------------------

STATUS_OUTPUT = {
    "type": "object",
    "properties": {
        "charger": {
            "type": "object",
            "properties": {
                "id": _API,
                "name": _API,
                "device_id": _API,
                "model": {"type": "string"},
                "firmware": _API,
                "online": {"type": "boolean"},
                "active": {"type": "boolean"},
            },
            "required": ["id", "name", "model", "online", "active"],
        },
        "operating_mode": _MODE,
        "charging": {
            "type": "object",
            "properties": {
                "power_kw": _NUM,
                "session_energy_kwh": _NUM,
                "charge_current_set_a": _NUM,
                "active_phases": _STR_LIST,
                "final_stop_active": _BOOL,
                "current_a": _PHASES,
                "voltage_v": _PHASES,
                "cable_rating_a": _INT,
                "charger_max_current_a": _NUM,
                "charger_min_current_a": _NUM,
            },
            "required": ["power_kw", "session_energy_kwh", "active_phases", "final_stop_active"],
        },
        "installation": {
            "type": "object",
            "properties": {
                "id": _API,
                "name": _API,
                "available_current_a": _API,
                "max_current_a": _API,
                "available_current_mode": {"type": "string"},
            },
            "required": ["id", "available_current_a", "max_current_a", "available_current_mode"],
        },
        "diagnostics": {
            "type": "object",
            "properties": {
                "temperature_internal_c": _NUM,
                "humidity_pct": _NUM,
                "signal_strength_dbm": _NUM,
                "communication_mode": _STR,
                "warnings": _STR,
            },
        },
        "authorization_required": {"type": "boolean"},
        "observed_at": _STR,
    },
    "required": ["charger", "operating_mode", "charging", "installation", "diagnostics"],
}

_CHARGER_SUMMARY = {
    "type": "object",
    "properties": {
        "id": _API,
        "name": _API,
        "device_id": _API,
        "model": {"type": "string"},
        "online": _API,
        "operating_mode": {"type": "string"},
    },
    "required": ["id", "name", "model", "operating_mode"],
}

INSTALLATION_OUTPUT = {
    "type": "object",
    "properties": {
        "id": _API,
        "name": _API,
        "address": {
            "type": "object",
            "properties": {"street": _API, "zip_code": _API, "city": _API},
        },
        "timezone": _API,
        "max_current_a": _API,
        "available_current_a": _API,
        "available_current_phases_a": _API_PHASES,
        "available_current_mode": {"type": "string"},
        "network_type": {"type": "string"},
        "use_load_balancing": _API,
        "authentication_required": {"type": "boolean"},
        "features_available": _STR_LIST,
        "features_enabled": _STR_LIST,
        "circuits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": _API,
                    "name": _API,
                    "max_current_a": _API,
                    "active": _API,
                    "chargers": {"type": "array", "items": _CHARGER_SUMMARY},
                },
                "required": ["id", "name", "chargers"],
            },
        },
    },
    "required": ["id", "name", "max_current_a", "available_current_a", "circuits"],
}

HISTORY_OUTPUT = {
    "type": "object",
    "properties": {
        "time_range": {"type": "string"},
        "start": {"type": "string", "format": "date-time"},
        "end": {"type": "string", "format": "date-time"},
        "timezone": {"type": "string"},
        "summary": {
            "type": "object",
            "properties": {
                "session_count": {"type": "integer"},
                "energy_kwh": {"type": "number"},
                "duration_hours": {"type": "number"},
                "cost": {"type": "number", "description": "Only with ZAPTEC_PRICE_PER_KWH"},
                "price_per_kwh": {"type": "number"},
                "currency": {"type": "string"},
            },
            "required": ["session_count", "energy_kwh", "duration_hours"],
        },
        "sessions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": _API,
                    "start": {"type": "string", "format": "date-time"},
                    "end": _STR,
                    "duration_minutes": _INT,
                    "energy_kwh": {"type": "number"},
                    "charger_name": _API,
                    "stopped_by_rfid": {"type": "boolean"},
                    "offline": {"type": "boolean"},
                    "aborted": {"type": "boolean"},
                    "cost": {"type": "number"},
                },
                "required": ["id", "start", "end", "duration_minutes", "energy_kwh"],
            },
        },
        "truncated": {"type": "boolean"},
    },
    "required": ["time_range", "start", "end", "timezone", "summary", "sessions", "truncated"],
}

COMMAND_OUTPUT = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "command": {"type": "string", "enum": ["pause", "resume"]},
        "charger": _REF,
        "previous_state": _MODE_WITH_STOP,
        "note": {"type": "string"},
    },
    "required": ["ok", "command", "charger", "previous_state", "note"],
}

CURRENT_OUTPUT = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "installation": _REF,
        "previous_available_current_a": _API,
        "requested_available_current_a": _NUM,
        "new_available_current_a": _API,
        "max_current_a": _API,
        "note": {"type": "string"},
    },
    "required": [
        "ok",
        "installation",
        "previous_available_current_a",
        "requested_available_current_a",
        "new_available_current_a",
        "max_current_a",
        "note",
    ],
}

# -- tool definitions ---------------------------------------------------------

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def tool_definitions() -> list[Tool]:
    return [
        Tool(
            name="zaptec_get_status",
            title="Get charger status",
            description=(
                "Current snapshot of the Zaptec charger: operating mode (disconnected / "
                "connected_requesting / connected_charging / connected_finished), charging power, "
                "session energy, per-phase current and voltage, cable, diagnostics, and the "
                "installation's available current. Read-only."
            ),
            input_schema={
                "type": "object",
                "properties": {"charger_id": _CHARGER_ID},
                "additionalProperties": False,
            },
            output_schema=STATUS_OUTPUT,
            annotations=_READ_ONLY,
        ),
        Tool(
            name="zaptec_get_installation",
            title="Get installation details",
            description=(
                "Installation details: address, timezone, main fuse / max current, available "
                "current and mode, load balancing, authentication, enabled features, circuits and "
                "chargers. Read-only."
            ),
            input_schema={
                "type": "object",
                "properties": {"installation_id": _INSTALLATION_ID},
                "additionalProperties": False,
            },
            output_schema=INSTALLATION_OUTPUT,
            annotations=_READ_ONLY,
        ),
        Tool(
            name="zaptec_get_charge_history",
            title="Get charging history",
            description=(
                "Completed charging sessions in a time range (installation-local time) with "
                "start, end, duration and energy in kWh, plus a summary. Cost fields appear only "
                "when ZAPTEC_PRICE_PER_KWH is configured. Read-only."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "charger_id": _CHARGER_ID,
                    "time_range": {
                        "type": "string",
                        "enum": ["today", "yesterday", "week", "month", "year", "custom"],
                        "default": "month",
                    },
                    "start_date": {
                        "type": "string",
                        "format": "date",
                        "description": "ISO date (YYYY-MM-DD), required for custom",
                    },
                    "end_date": {
                        "type": "string",
                        "format": "date",
                        "description": "ISO date (YYYY-MM-DD, inclusive), required for custom",
                    },
                },
                "if": {
                    "properties": {"time_range": {"const": "custom"}},
                    "required": ["time_range"],
                },
                "then": {"required": ["start_date", "end_date"]},
                "additionalProperties": False,
            },
            output_schema=HISTORY_OUTPUT,
            annotations=_READ_ONLY,
        ),
        Tool(
            name="zaptec_pause_charging",
            title="Pause charging",
            description=(
                "CHANGES STATE: pause the running charging session (Zaptec command 506). Only "
                "valid while the charger is in connected_charging; otherwise returns an "
                "explanation."
            ),
            input_schema={
                "type": "object",
                "properties": {"charger_id": _CHARGER_ID},
                "additionalProperties": False,
            },
            output_schema=COMMAND_OUTPUT,
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=True,
            ),
        ),
        Tool(
            name="zaptec_resume_charging",
            title="Resume charging",
            description=(
                "CHANGES STATE: resume a session that was paused via the app or this server "
                "(Zaptec command 507). Only valid when the charger is connected_finished with "
                "final_stop_active; otherwise returns an explanation."
            ),
            input_schema={
                "type": "object",
                "properties": {"charger_id": _CHARGER_ID},
                "additionalProperties": False,
            },
            output_schema=COMMAND_OUTPUT,
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=True,
            ),
        ),
        Tool(
            name="zaptec_set_available_current",
            title="Set available current",
            description=(
                "CHANGES STATE: set the installation's available charging current in amps (all "
                "phases), or null to reset to the installation maximum. Zaptec recommends at most "
                "one change per 15 minutes; the server refuses faster changes unless force=true."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "amps": {
                        "type": ["number", "null"],
                        "minimum": 0,
                        "description": (
                            "Amps between 0 and the installation max current, or null to reset."
                        ),
                    },
                    "installation_id": _INSTALLATION_ID,
                    "force": {"type": "boolean", "default": False},
                },
                "required": ["amps"],
                "additionalProperties": False,
            },
            output_schema=CURRENT_OUTPUT,
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=True,
                idempotent_hint=True,
                open_world_hint=True,
            ),
        ),
    ]


# The v2 SDK no longer validates arguments against inputSchema; do it here.
_VALIDATORS = {
    t.name: Draft202012Validator(t.input_schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    for t in tool_definitions()
}


async def dispatch(tools: ZaptecTools, name: str, arguments: dict[str, Any] | None) -> Any:
    """Route a call to ZaptecTools. Raises ZaptecError/ValueError on failure."""
    a = arguments or {}
    if name == "zaptec_get_status":
        return await tools.get_status(charger_id=a.get("charger_id"))
    if name == "zaptec_get_installation":
        return await tools.get_installation(installation_id=a.get("installation_id"))
    if name == "zaptec_get_charge_history":
        return await tools.get_charge_history(
            charger_id=a.get("charger_id"),
            time_range=a.get("time_range") or "month",
            start_date=a.get("start_date"),
            end_date=a.get("end_date"),
        )
    if name == "zaptec_pause_charging":
        return await tools.pause_charging(charger_id=a.get("charger_id"))
    if name == "zaptec_resume_charging":
        return await tools.resume_charging(charger_id=a.get("charger_id"))
    if name == "zaptec_set_available_current":
        return await tools.set_available_current(
            a.get("amps"),
            installation_id=a.get("installation_id"),
            force=bool(a.get("force", False)),
        )
    raise MCPError(INVALID_PARAMS, f"Unknown tool: {name}")


def _json(value: Any) -> str:
    return json.dumps(value, default=str, indent=2)


def _error(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=_json(payload))], is_error=True)


async def call_tool(
    tools: ZaptecTools, name: str, arguments: dict[str, Any] | None
) -> CallToolResult:
    """Run a tool and build its result.

    Failures the model can act on (invalid arguments, API errors, guards) become
    tool execution errors (`isError: true`) with a JSON payload. Unknown tools
    raise MCPError, which the SDK sends as a JSON-RPC protocol error.
    """
    validator = _VALIDATORS.get(name)
    if validator is None:
        raise MCPError(INVALID_PARAMS, f"Unknown tool: {name}")
    problems = sorted(validator.iter_errors(arguments or {}), key=lambda e: list(e.path))
    if problems:
        payload = {
            "error_type": "InputValidationError",
            "message": "; ".join(e.message for e in problems),
        }
        return _error(payload)
    try:
        result = await dispatch(tools, name, arguments)
    except ZaptecError as exc:
        log.warning("tool %s failed: %s", name, type(exc).__name__)
        return _error({"error_type": type(exc).__name__, "message": str(exc), **exc.payload})
    except ValueError as exc:
        return _error({"error_type": "ValueError", "message": str(exc)})
    # Round-trip through JSON so structuredContent holds plain JSON values only.
    text = _json(result)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=json.loads(text),
        is_error=False,
    )
