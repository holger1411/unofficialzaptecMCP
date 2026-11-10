"""MCP entry point: server wiring and stdio transport."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any, NoReturn

from mcp.server import CacheHint, Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams

from . import __version__
from .cache.manager import CacheManager
from .config import ServerConfig, env_file_permission_warning, load_dotenv, resolve_env_file
from .server import ZaptecTools
from .tool_defs import call_tool, tool_definitions
from .utils.errors import ZaptecError
from .utils.logging import SecretRedactor, configure_logging
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


def load_config() -> tuple[ServerConfig, Path]:
    """Load the env file (ZAPTEC_ENV_FILE or ./.env) and build the config.

    Raises ZaptecError/ValueError/OSError for anything misconfigured.
    """
    env_file = resolve_env_file()
    load_dotenv(env_file)
    return ServerConfig.from_env(), env_file


def _setup_logging(cfg: ServerConfig, env_file: Path) -> SecretRedactor:
    redactor = configure_logging(cfg.log_level)
    redactor.add(cfg.password)
    redactor.add(cfg.username)
    warning = env_file_permission_warning(env_file)
    if warning:
        log.warning("%s", warning)
    return redactor


def _config_error(exc: BaseException) -> NoReturn:
    # One line on stderr; stdout carries JSON-RPC and must stay untouched.
    message = " ".join(str(exc).split()) or type(exc).__name__
    print(f"unofficial-zaptec-mcp: configuration error: {message}", file=sys.stderr)
    sys.exit(2)


async def _run(cfg: ServerConfig, env_file: Path) -> None:
    _setup_logging(cfg, env_file)

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
        cfg, env_file = load_config()
    except (ZaptecError, ValueError, OSError) as exc:
        _config_error(exc)
    try:
        asyncio.run(_run(cfg, env_file))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
