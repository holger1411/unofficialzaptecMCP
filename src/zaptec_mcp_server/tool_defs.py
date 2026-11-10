"""MCP tool definitions (input/output schemas, annotations) and dispatch to ZaptecTools."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult, TextContent, Tool, ToolAnnotations

from .server import ZaptecTools
from .utils.errors import ZaptecError

log = logging.getLogger("zaptec_mcp_server")

# -- shared schema fragments --------------------------------------------------

# Zaptec ids are UUIDs; anything else is rejected before it can reach a URL path.
UUID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
# minLength/maxLength: Python's re lets "$" match before a trailing newline.
_UUID: dict[str, Any] = {
    "type": "string",
    "format": "uuid",
    "pattern": UUID_PATTERN,
    "minLength": 36,
    "maxLength": 36,
}
_CHARGER_ID = {
    **_UUID,
    "description": (
        "Optional charger id (UUID). Defaults to ZAPTEC_DEFAULT_CHARGER_ID or the only charger."
    ),
}
_INSTALLATION_ID = {
    **_UUID,
    "description": (
        "Optional installation id (UUID). Defaults to the installation of the default charger."
    ),
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
                "active_phases": {
                    **_STR_LIST,
                    "description": "Phases the charger is set to use (L1, L2, L3)",
                },
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
        "observed_at": {**_STR, "description": "Newest observation, ISO 8601 with offset"},
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
        "truncated": {
            "type": "boolean",
            "description": "True if sessions were left out; truncated_by says why.",
        },
        "truncated_by": {
            "type": "array",
            "items": {"type": "string", "enum": ["display_limit", "api_page_limit"]},
            "description": (
                "display_limit: only the first 500 sessions are listed (summary covers all "
                "retrieved). api_page_limit: the API had more sessions than were fetched "
                "(summary is incomplete; narrow the range)."
            ),
        },
        "truncation_note": {"type": "string"},
    },
    "required": [
        "time_range",
        "start",
        "end",
        "timezone",
        "summary",
        "sessions",
        "truncated",
        "truncated_by",
    ],
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

# -- tool registry -------------------------------------------------------------

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
_STATE_CHANGING = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
_DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True
)

Handler = Callable[[ZaptecTools, dict[str, Any]], Awaitable[Any]]


def _object(properties: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Closed input object schema; `extra` adds keywords such as required/if/then."""
    return {"type": "object", "properties": properties, **extra, "additionalProperties": False}


# Custom ranges need both dates ("if"/"then" are Python keywords, hence the dict).
_CUSTOM_NEEDS_DATES: dict[str, Any] = {
    "if": {"properties": {"time_range": {"const": "custom"}}, "required": ["time_range"]},
    "then": {"required": ["start_date", "end_date"]},
}


async def _get_status(t: ZaptecTools, a: dict[str, Any]) -> Any:
    return await t.get_status(charger_id=a.get("charger_id"))


async def _get_installation(t: ZaptecTools, a: dict[str, Any]) -> Any:
    return await t.get_installation(installation_id=a.get("installation_id"))


async def _get_charge_history(t: ZaptecTools, a: dict[str, Any]) -> Any:
    return await t.get_charge_history(
        charger_id=a.get("charger_id"),
        time_range=a.get("time_range") or "month",
        start_date=a.get("start_date"),
        end_date=a.get("end_date"),
    )


async def _pause_charging(t: ZaptecTools, a: dict[str, Any]) -> Any:
    return await t.pause_charging(charger_id=a.get("charger_id"))


async def _resume_charging(t: ZaptecTools, a: dict[str, Any]) -> Any:
    return await t.resume_charging(charger_id=a.get("charger_id"))


async def _set_available_current(t: ZaptecTools, a: dict[str, Any]) -> Any:
    return await t.set_available_current(
        a.get("amps"),
        installation_id=a.get("installation_id"),
        force=bool(a.get("force", False)),
    )


@dataclass(frozen=True)
class _Entry:
    tool: Tool
    handler: Handler
    validator: Draft202012Validator


def _entry(tool: Tool, handler: Handler) -> _Entry:
    # The v2 SDK no longer validates arguments against inputSchema; do it here.
    validator = Draft202012Validator(
        tool.input_schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return _Entry(tool, handler, validator)


_ENTRIES = (
    _entry(
        Tool(
            name="zaptec_get_status",
            title="Get charger status",
            description=(
                "Current snapshot of the Zaptec charger: operating mode (disconnected / "
                "connected_requesting / connected_charging / connected_finished), charging power, "
                "session energy, per-phase current and voltage, cable, diagnostics, and the "
                "installation's available current. Read-only."
            ),
            input_schema=_object({"charger_id": _CHARGER_ID}),
            output_schema=STATUS_OUTPUT,
            annotations=_READ_ONLY,
        ),
        _get_status,
    ),
    _entry(
        Tool(
            name="zaptec_get_installation",
            title="Get installation details",
            description=(
                "Installation details: address, timezone, main fuse / max current, available "
                "current and mode, load balancing, authentication, enabled features, circuits and "
                "chargers. Read-only."
            ),
            input_schema=_object({"installation_id": _INSTALLATION_ID}),
            output_schema=INSTALLATION_OUTPUT,
            annotations=_READ_ONLY,
        ),
        _get_installation,
    ),
    _entry(
        Tool(
            name="zaptec_get_charge_history",
            title="Get charging history",
            description=(
                "Completed charging sessions in a time range (installation-local time) with "
                "start, end, duration and energy in kWh, plus a summary. Cost fields appear only "
                "when ZAPTEC_PRICE_PER_KWH is configured. Custom ranges may span at most 366 "
                "days. If truncated is true, truncated_by says whether the session list or the "
                "summary is incomplete. Read-only."
            ),
            input_schema=_object(
                {
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
                        "description": (
                            "ISO date (YYYY-MM-DD, inclusive, not before start_date), "
                            "required for custom"
                        ),
                    },
                },
                **_CUSTOM_NEEDS_DATES,
            ),
            output_schema=HISTORY_OUTPUT,
            annotations=_READ_ONLY,
        ),
        _get_charge_history,
    ),
    _entry(
        Tool(
            name="zaptec_pause_charging",
            title="Pause charging",
            description=(
                "CHANGES STATE: pause the running charging session (Zaptec command 506). Only "
                "valid while the charger is in connected_charging; otherwise returns an "
                "explanation."
            ),
            input_schema=_object({"charger_id": _CHARGER_ID}),
            output_schema=COMMAND_OUTPUT,
            annotations=_STATE_CHANGING,
        ),
        _pause_charging,
    ),
    _entry(
        Tool(
            name="zaptec_resume_charging",
            title="Resume charging",
            description=(
                "CHANGES STATE: resume a session that was paused via the app or this server "
                "(Zaptec command 507). Only valid when the charger is connected_finished with "
                "final_stop_active; otherwise returns an explanation."
            ),
            input_schema=_object({"charger_id": _CHARGER_ID}),
            output_schema=COMMAND_OUTPUT,
            annotations=_STATE_CHANGING,
        ),
        _resume_charging,
    ),
    _entry(
        Tool(
            name="zaptec_set_available_current",
            title="Set available current",
            description=(
                "CHANGES STATE: set the installation's available charging current in amps (all "
                "phases), or null to reset to the installation maximum. 0 A stops charging on "
                "every charger of the installation until the current is raised again. Zaptec "
                "recommends at most one change per 15 minutes; the server refuses faster changes "
                "unless force=true."
            ),
            input_schema=_object(
                {
                    "amps": {
                        "type": ["number", "null"],
                        "minimum": 0,
                        "description": (
                            "Amps between 0 and the installation max current, or null to reset. "
                            "0 stops charging for the whole installation."
                        ),
                    },
                    "installation_id": _INSTALLATION_ID,
                    "force": {"type": "boolean", "default": False},
                },
                required=["amps"],
            ),
            output_schema=CURRENT_OUTPUT,
            annotations=_DESTRUCTIVE,
        ),
        _set_available_current,
    ),
)

# Single source of truth: tools/list and tools/call both read this table.
_REGISTRY: dict[str, _Entry] = {e.tool.name: e for e in _ENTRIES}


def tool_definitions() -> list[Tool]:
    return [e.tool.model_copy(deep=True) for e in _REGISTRY.values()]


def _lookup(name: str) -> _Entry:
    entry = _REGISTRY.get(name)
    if entry is None:
        raise MCPError(INVALID_PARAMS, f"Unknown tool: {name}")
    return entry


async def dispatch(tools: ZaptecTools, name: str, arguments: dict[str, Any] | None) -> Any:
    """Route a call to ZaptecTools. Raises ZaptecError/ValueError on failure."""
    return await _lookup(name).handler(tools, arguments or {})


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
    entry = _lookup(name)
    problems = sorted(entry.validator.iter_errors(arguments or {}), key=lambda e: list(e.path))
    if problems:
        payload = {
            "error_type": "InputValidationError",
            "message": "; ".join(e.message for e in problems),
        }
        return _error(payload)
    try:
        result = await entry.handler(tools, arguments or {})
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
