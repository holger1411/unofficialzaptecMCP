"""MCP entry point: tool definitions, dispatch and stdio transport."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .cache.manager import CacheManager
from .config import ServerConfig, load_dotenv
from .server import ZaptecTools
from .utils.errors import ZaptecError
from .utils.logging import configure_logging
from .zaptec.client import ZaptecClient

log = logging.getLogger("zaptec_mcp_server")

_CHARGER_ID = {
    "type": "string",
    "description": "Optional charger id. Defaults to ZAPTEC_DEFAULT_CHARGER_ID or the only charger.",
}
_INSTALLATION_ID = {
    "type": "string",
    "description": "Optional installation id. Defaults to the installation of the default charger.",
}


def tool_definitions() -> list[Tool]:
    return [
        Tool(
            name="zaptec_get_status",
            description=(
                "Current snapshot of the Zaptec charger: operating mode (disconnected / "
                "connected_requesting / connected_charging / connected_finished), charging power, "
                "session energy, per-phase current and voltage, cable, diagnostics, and the "
                "installation's available current. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {"charger_id": _CHARGER_ID},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="zaptec_get_installation",
            description=(
                "Installation details: address, timezone, main fuse / max current, available "
                "current and mode, load balancing, authentication, enabled features, circuits and "
                "chargers. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {"installation_id": _INSTALLATION_ID},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="zaptec_get_charge_history",
            description=(
                "Completed charging sessions in a time range (installation-local time) with "
                "start, end, duration and energy in kWh, plus a summary. Cost fields appear only "
                "when ZAPTEC_PRICE_PER_KWH is configured. Read-only."
            ),
            inputSchema={
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
                        "description": "ISO date, required for custom",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "ISO date (inclusive), required for custom",
                    },
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="zaptec_pause_charging",
            description=(
                "CHANGES STATE: pause the running charging session (Zaptec command 506). Only "
                "valid while the charger is in connected_charging; otherwise returns an "
                "explanation."
            ),
            inputSchema={
                "type": "object",
                "properties": {"charger_id": _CHARGER_ID},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="zaptec_resume_charging",
            description=(
                "CHANGES STATE: resume a session that was paused via the app or this server "
                "(Zaptec command 507). Only valid when the charger is connected_finished with "
                "final_stop_active; otherwise returns an explanation."
            ),
            inputSchema={
                "type": "object",
                "properties": {"charger_id": _CHARGER_ID},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="zaptec_set_available_current",
            description=(
                "CHANGES STATE: set the installation's available charging current in amps (all "
                "phases), or null to reset to the installation maximum. Zaptec recommends at most "
                "one change per 15 minutes; the server refuses faster changes unless force=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "amps": {
                        "type": ["number", "null"],
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
        ),
    ]


async def dispatch(tools: ZaptecTools, name: str, arguments: dict[str, Any] | None) -> Any:
    a = arguments or {}
    try:
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
        raise ZaptecError(f"unknown tool: {name}")
    except ZaptecError as exc:
        payload = {"error_type": type(exc).__name__, "message": str(exc), **exc.payload}
        log.warning("tool %s failed: %s", name, type(exc).__name__)
        raise RuntimeError(json.dumps(payload, default=str)) from exc
    except ValueError as exc:
        raise RuntimeError(json.dumps({"error_type": "ValueError", "message": str(exc)})) from exc


async def _run() -> None:
    load_dotenv(Path(".env"))
    cfg = ServerConfig.from_env()
    redactor = configure_logging(cfg.log_level)
    redactor.add(cfg.password)
    redactor.add(cfg.username)

    client = ZaptecClient(cfg)
    tools = ZaptecTools(client=client, cache=CacheManager(enabled=cfg.cache_enabled), cfg=cfg)
    server: Server = Server("unofficial-zaptec-mcp")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[Tool]:
        return tool_definitions()

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = await dispatch(tools, name, arguments)
        return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(signum: int) -> None:
        log.info("received signal %s, shutting down", signum)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown, sig)
        except NotImplementedError:
            pass  # Windows

    async with stdio_server() as (reader, writer):
        runner = asyncio.create_task(
            server.run(reader, writer, server.create_initialization_options())
        )
        stop_task = asyncio.create_task(stop_event.wait())
        _done, pending = await asyncio.wait({runner, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await client.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
