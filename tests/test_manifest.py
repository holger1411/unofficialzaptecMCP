"""The MCPB manifest must stay in sync with the package."""

from __future__ import annotations

import json
from pathlib import Path

from zaptec_mcp_server import __version__
from zaptec_mcp_server.tool_defs import tool_definitions

MANIFEST = json.loads((Path(__file__).parent.parent / "manifest.json").read_text(encoding="utf-8"))


def test_tool_names_match_server() -> None:
    assert [t["name"] for t in MANIFEST["tools"]] == [t.name for t in tool_definitions()]


def test_version_matches_package() -> None:
    assert MANIFEST["version"] == __version__


def test_password_is_sensitive_and_credentials_are_mapped() -> None:
    config = MANIFEST["user_config"]
    assert config["zaptec_password"]["sensitive"] is True
    env = MANIFEST["server"]["mcp_config"]["env"]
    assert env["ZAPTEC_USERNAME"] == "${user_config.zaptec_username}"
    assert env["ZAPTEC_PASSWORD"] == "${user_config.zaptec_password}"
