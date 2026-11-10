"""Manual live probe. Usage: python scripts/probe.py [--dump DIR]

Logs in with the .env credentials, prints the formatted status and optionally
dumps raw responses (chargers, state, installation, hierarchy, sessions) to
DIR for later sanitizing with scripts/sanitize_fixture.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zaptec_mcp_server.config import ServerConfig, load_dotenv, resolve_env_file
from zaptec_mcp_server.utils.logging import configure_logging
from zaptec_mcp_server.zaptec.client import ZaptecClient
from zaptec_mcp_server.zaptec.formatters import format_status
from zaptec_mcp_server.zaptec.observations import field


async def main(dump: Path | None) -> None:
    load_dotenv(resolve_env_file())
    cfg = ServerConfig.from_env()
    redactor = configure_logging("INFO")
    redactor.add(cfg.password)
    redactor.add(cfg.username)
    client = ZaptecClient(cfg)
    try:
        charger = await client.resolve_charger()
        cid = field(charger, "Id")
        state = await client.get_charger_state(cid)
        installation = await client.resolve_installation(charger=charger)
        iid = field(installation, "Id")
        hierarchy = await client.get_hierarchy(iid)
        now = datetime.now(UTC)
        history = await client.archived_sessions(
            start=now - timedelta(days=30), end=now, charger_id=cid
        )
        sessions = history.sessions
        print(json.dumps(format_status(charger, state, installation), indent=2))
        more = " (truncated: the API reported more)" if history.truncated else ""
        print(f"{len(sessions)} sessions in the last 30 days{more}")
        if dump:
            dump.mkdir(parents=True, exist_ok=True)
            chargers = await client.list_chargers()
            (dump / "chargers.json").write_text(json.dumps({"Data": chargers}, indent=1))
            (dump / "charger_state.json").write_text(json.dumps(state, indent=1))
            (dump / "installation.json").write_text(json.dumps(installation, indent=1))
            (dump / "hierarchy.json").write_text(json.dumps(hierarchy, indent=1))
            (dump / "sessions_archived.json").write_text(
                json.dumps({"sessions": sessions, "cursor": None, "hasMore": False}, indent=1)
            )
            print(f"raw responses written to {dump} - sanitize before committing!")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, default=None)
    asyncio.run(main(parser.parse_args().dump))
