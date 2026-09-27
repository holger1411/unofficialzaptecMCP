"""MCP entry point: server wiring and stdio transport."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from mcp.server import CacheHint, Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams

from . import __version__
from .cache.manager import CacheManager
from .config import ServerConfig, load_dotenv
from .server import ZaptecTools
from .tool_defs import call_tool, tool_definitions
from .utils.logging import configure_logging
from .zaptec.client import ZaptecClient

log = logging.getLogger("zaptec_mcp_server")

# The tool list is static, so clients may cache tools/list (spec 2026-07-28 ttlMs/cacheScope).
TOOLS_LIST_TTL_MS = 3_600_000


def build_server(tools: ZaptecTools) -> Server[Any]:
    async def handle_list_tools(
        ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=tool_definitions())

    async def handle_call_tool(
        ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult:
        return await call_tool(tools, params.name, params.arguments)

    return Server(
        "unofficial-zaptec-mcp",
        version=__version__,
        title="Unofficial Zaptec MCP",
        cache_hints={"tools/list": CacheHint(ttl_ms=TOOLS_LIST_TTL_MS, scope="public")},
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )


async def _run() -> None:
    load_dotenv(Path(".env"))
    cfg = ServerConfig.from_env()
    redactor = configure_logging(cfg.log_level)
    redactor.add(cfg.password)
    redactor.add(cfg.username)

    client = ZaptecClient(cfg)
    tools = ZaptecTools(client=client, cache=CacheManager(enabled=cfg.cache_enabled), cfg=cfg)
    server = build_server(tools)

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
