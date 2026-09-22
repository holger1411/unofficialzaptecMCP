"""Live tests against the Zaptec cloud. Opt in with `pytest -m integration`; needs .env."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from zaptec_mcp_server.cache.manager import CacheManager
from zaptec_mcp_server.config import ServerConfig, load_dotenv
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.zaptec.client import ZaptecClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def tools() -> AsyncIterator[ZaptecTools]:
    load_dotenv(Path(".env"))
    try:
        cfg = ServerConfig.from_env()
    except Exception:
        pytest.skip("no credentials in environment")
    client = ZaptecClient(cfg)
    yield ZaptecTools(client=client, cache=CacheManager(), cfg=cfg)
    await client.close()


async def test_live_status(tools: ZaptecTools) -> None:
    out = await tools.get_status()
    assert out["charger"]["id"]
    assert out["operating_mode"]["name"] in {
        "unknown",
        "disconnected",
        "connected_requesting",
        "connected_charging",
        "connected_finished",
    }


async def test_live_installation(tools: ZaptecTools) -> None:
    out = await tools.get_installation()
    assert out["timezone"]
    assert out["circuits"]


async def test_live_history(tools: ZaptecTools) -> None:
    out = await tools.get_charge_history(time_range="month")
    assert out["summary"]["session_count"] >= 0
