from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from tests.test_client import FakeApi, make_client
from zaptec_mcp_server.config import ServerConfig
from zaptec_mcp_server.utils.errors import ZaptecNotFoundError
from zaptec_mcp_server.zaptec.client import CMD_PAUSE, ZaptecClient

C1 = {"Id": "c1", "Name": "Garage", "InstallationId": "i1"}
C2 = {"Id": "c2", "Name": "Carport", "InstallationId": "i1"}


async def test_list_endpoints_unwrap_data_and_cache() -> None:
    api = FakeApi(
        {
            ("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1]})],
            ("GET", "/api/installation"): [httpx.Response(200, json={"Data": [{"Id": "i1"}]})],
        }
    )
    client = make_client(api)
    assert await client.list_chargers() == [C1]
    assert await client.list_chargers() == [C1]
    assert await client.list_installations() == [{"Id": "i1"}]
    assert len([c for c in api.calls if c.url.path == "/api/chargers"]) == 1
    client.invalidate_lists()
    await client.list_chargers()
    assert len([c for c in api.calls if c.url.path == "/api/chargers"]) == 2


async def test_resolve_charger_single_default_and_explicit() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1]})]})
    client = make_client(api)
    assert (await client.resolve_charger())["Id"] == "c1"
    assert (await client.resolve_charger("c1"))["Name"] == "Garage"
    with pytest.raises(ZaptecNotFoundError) as info:
        await client.resolve_charger("zzz")
    assert info.value.payload["chargers"] == [{"id": "c1", "name": "Garage"}]


async def test_resolve_charger_multiple_requires_choice() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1, C2]})]})
    client = make_client(api)
    with pytest.raises(ZaptecNotFoundError):
        await client.resolve_charger()
    cfg = ServerConfig.from_env(
        {"ZAPTEC_USERNAME": "u", "ZAPTEC_PASSWORD": "pw123456", "ZAPTEC_DEFAULT_CHARGER_ID": "c2"}
    )
    client2 = ZaptecClient(cfg, transport=api.transport())
    assert (await client2.resolve_charger())["Id"] == "c2"


async def test_resolve_charger_none_available() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": []})]})
    client = make_client(api)
    with pytest.raises(ZaptecNotFoundError):
        await client.resolve_charger()


async def test_resolve_installation_from_charger_and_explicit() -> None:
    api = FakeApi(
        {
            ("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1]})],
            ("GET", "/api/installation/i1"): [
                httpx.Response(200, json={"Id": "i1", "Name": "Home"})
            ],
            ("GET", "/api/installation/i9"): [httpx.Response(404)],
        }
    )
    client = make_client(api)
    assert (await client.resolve_installation())["Name"] == "Home"
    assert (await client.resolve_installation(charger=C1))["Id"] == "i1"
    with pytest.raises(ZaptecNotFoundError):
        await client.resolve_installation("i9")


async def test_send_command_and_update_installation_paths() -> None:
    api = FakeApi(
        {
            ("POST", "/api/chargers/c1/sendCommand/506"): [httpx.Response(200)],
            ("POST", "/api/installation/i1/update"): [httpx.Response(200)],
        }
    )
    client = make_client(api)
    await client.send_command("c1", CMD_PAUSE)
    await client.update_installation("i1", {"availableCurrent": 10})
    posts = [c for c in api.calls if c.method == "POST" and "oauth" not in c.url.path]
    assert [p.url.path for p in posts] == [
        "/api/chargers/c1/sendCommand/506",
        "/api/installation/i1/update",
    ]


async def test_archived_sessions_follows_cursor_and_caps() -> None:
    pages = [
        httpx.Response(200, json={"sessions": [{"id": "s1"}], "cursor": "abc", "hasMore": True}),
        httpx.Response(200, json={"sessions": [{"id": "s2"}], "cursor": None, "hasMore": False}),
    ]
    api = FakeApi({("GET", "/api/sessions/archived"): pages})
    client = make_client(api)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    sessions = await client.archived_sessions(start=start, end=end, charger_id="c1")
    assert [s["id"] for s in sessions] == ["s1", "s2"]
    calls = [c for c in api.calls if c.url.path == "/api/sessions/archived"]
    assert calls[0].url.params["From"] == "2026-09-01T00:00:00Z"
    assert calls[0].url.params["To"] == "2026-09-22T12:00:00Z"
    assert calls[0].url.params["ChargerId"] == "c1"
    assert calls[0].url.params["PageSize"] == "200"
    assert calls[1].url.params["Cursor"] == "abc"


async def test_archived_sessions_max_pages() -> None:
    page = httpx.Response(200, json={"sessions": [{"id": "s"}], "cursor": "x", "hasMore": True})
    api = FakeApi({("GET", "/api/sessions/archived"): [page]})
    client = make_client(api)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 2, tzinfo=timezone.utc)
    sessions = await client.archived_sessions(start=start, end=end, charger_id="c1", max_pages=2)
    assert len(sessions) == 2
