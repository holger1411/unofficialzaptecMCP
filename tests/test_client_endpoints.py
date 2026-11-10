from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tests.test_client import FakeApi, make_client
from zaptec_mcp_server.config import ServerConfig
from zaptec_mcp_server.utils.errors import ZaptecGuardError, ZaptecNotFoundError
from zaptec_mcp_server.zaptec.client import CMD_PAUSE, ArchivedSessions, ZaptecClient

CID1 = "00000001-0000-4000-8000-000000000001"
CID2 = "00000002-0000-4000-8000-000000000002"
IID1 = "00000003-0000-4000-8000-000000000003"
IID9 = "00000009-0000-4000-8000-000000000009"
C1 = {"Id": CID1, "Name": "Garage", "InstallationId": IID1}
C2 = {"Id": CID2, "Name": "Carport", "InstallationId": IID1}


async def test_list_endpoints_unwrap_data_and_cache() -> None:
    api = FakeApi(
        {
            ("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1]})],
            ("GET", "/api/installation"): [httpx.Response(200, json={"Data": [{"Id": IID1}]})],
        }
    )
    client = make_client(api)
    assert await client.list_chargers() == [C1]
    assert await client.list_chargers() == [C1]
    assert await client.list_installations() == [{"Id": IID1}]
    assert len([c for c in api.calls if c.url.path == "/api/chargers"]) == 1
    client.invalidate_lists()
    await client.list_chargers()
    assert len([c for c in api.calls if c.url.path == "/api/chargers"]) == 2


async def test_resolve_charger_single_default_and_explicit() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1]})]})
    client = make_client(api)
    assert (await client.resolve_charger())["Id"] == CID1
    assert (await client.resolve_charger(CID1))["Name"] == "Garage"
    with pytest.raises(ZaptecNotFoundError) as info:
        await client.resolve_charger("zzz")
    assert info.value.payload["chargers"] == [{"id": CID1, "name": "Garage"}]


async def test_resolve_charger_multiple_requires_choice() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1, C2]})]})
    client = make_client(api)
    with pytest.raises(ZaptecNotFoundError):
        await client.resolve_charger()
    cfg = ServerConfig.from_env(
        {"ZAPTEC_USERNAME": "u", "ZAPTEC_PASSWORD": "pw123456", "ZAPTEC_DEFAULT_CHARGER_ID": CID2}
    )
    client2 = ZaptecClient(cfg, transport=api.transport())
    assert (await client2.resolve_charger())["Id"] == CID2


async def test_resolve_charger_none_available() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": []})]})
    client = make_client(api)
    with pytest.raises(ZaptecNotFoundError):
        await client.resolve_charger()


async def test_resolve_installation_from_charger_and_explicit() -> None:
    api = FakeApi(
        {
            ("GET", "/api/chargers"): [httpx.Response(200, json={"Data": [C1]})],
            ("GET", f"/api/installation/{IID1}"): [
                httpx.Response(200, json={"Id": IID1, "Name": "Home"})
            ],
            ("GET", f"/api/installation/{IID9}"): [httpx.Response(404)],
        }
    )
    client = make_client(api)
    assert (await client.resolve_installation())["Name"] == "Home"
    assert (await client.resolve_installation(charger=C1))["Id"] == IID1
    with pytest.raises(ZaptecNotFoundError):
        await client.resolve_installation(IID9)


async def test_send_command_and_update_installation_paths() -> None:
    api = FakeApi(
        {
            ("POST", f"/api/chargers/{CID1}/sendCommand/506"): [httpx.Response(200)],
            ("POST", f"/api/installation/{IID1}/update"): [httpx.Response(200)],
        }
    )
    client = make_client(api)
    await client.send_command(CID1, CMD_PAUSE)
    await client.update_installation(IID1, {"availableCurrent": 10})
    posts = [c for c in api.calls if c.method == "POST" and "oauth" not in c.url.path]
    assert [p.url.path for p in posts] == [
        f"/api/chargers/{CID1}/sendCommand/506",
        f"/api/installation/{IID1}/update",
    ]


async def test_uppercase_uuid_accepted() -> None:
    upper = CID1.upper().replace("0000-4000", "ABCD-4000")
    api = FakeApi({("GET", f"/api/chargers/{upper}"): [httpx.Response(200, json={"Id": upper})]})
    client = make_client(api)
    assert (await client.get_charger(upper))["Id"] == upper


BAD_IDS = [
    "../chargers/c1/state?x=",
    "c1",
    "",
    f"{CID1}/../x",
    f"{CID1}\n",
    f" {CID1}",
    "00000001000040008000000000000001",  # no hyphens: not canonical
    "{00000001-0000-4000-8000-000000000001}",
    "0000000g-0000-4000-8000-000000000001",
]

Call = Callable[[ZaptecClient, str], Awaitable[Any]]
CALLS: dict[str, Call] = {
    "get_charger": lambda c, i: c.get_charger(i),
    "get_charger_state": lambda c, i: c.get_charger_state(i),
    "get_installation": lambda c, i: c.get_installation(i),
    "get_hierarchy": lambda c, i: c.get_hierarchy(i),
    "send_command": lambda c, i: c.send_command(i, CMD_PAUSE),
    "update_installation": lambda c, i: c.update_installation(i, {"availableCurrent": 6}),
}


@pytest.mark.parametrize("bad_id", BAD_IDS)
@pytest.mark.parametrize("name", sorted(CALLS))
async def test_non_uuid_ids_never_reach_the_api(name: str, bad_id: str) -> None:
    api = FakeApi({})
    client = make_client(api)
    with pytest.raises(ZaptecGuardError) as info:
        await CALLS[name](client, bad_id)
    assert "must be a UUID" in str(info.value)
    assert api.calls == []


async def test_resolve_installation_rejects_injected_ids() -> None:
    api = FakeApi({})
    client = make_client(api)
    with pytest.raises(ZaptecGuardError):
        await client.resolve_installation("../chargers/c1/state?x=")
    evil_charger = {"Id": CID1, "InstallationId": "../../api/chargers"}
    with pytest.raises(ZaptecGuardError):
        await client.resolve_installation(charger=evil_charger)
    assert api.calls == []


async def test_non_string_id_rejected() -> None:
    api = FakeApi({})
    client = make_client(api)
    with pytest.raises(ZaptecGuardError):
        await client.get_charger(123)  # type: ignore[arg-type]
    assert api.calls == []


async def test_archived_sessions_follows_cursor_and_caps() -> None:
    pages = [
        httpx.Response(200, json={"sessions": [{"id": "s1"}], "cursor": "abc", "hasMore": True}),
        httpx.Response(200, json={"sessions": [{"id": "s2"}], "cursor": None, "hasMore": False}),
    ]
    api = FakeApi({("GET", "/api/sessions/archived"): pages})
    client = make_client(api)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    result = await client.archived_sessions(start=start, end=end, charger_id=CID1)
    assert isinstance(result, ArchivedSessions)
    assert [s["id"] for s in result.sessions] == ["s1", "s2"]
    assert result.truncated is False
    calls = [c for c in api.calls if c.url.path == "/api/sessions/archived"]
    assert calls[0].url.params["From"] == "2026-09-01T00:00:00Z"
    assert calls[0].url.params["To"] == "2026-09-22T12:00:00Z"
    assert calls[0].url.params["ChargerId"] == CID1
    assert calls[0].url.params["PageSize"] == "200"
    assert calls[1].url.params["Cursor"] == "abc"


async def test_archived_sessions_max_pages_reports_truncation() -> None:
    page = httpx.Response(200, json={"sessions": [{"id": "s"}], "cursor": "x", "hasMore": True})
    api = FakeApi({("GET", "/api/sessions/archived"): [page]})
    client = make_client(api)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    result = await client.archived_sessions(start=start, end=end, charger_id=CID1, max_pages=2)
    assert len(result.sessions) == 2
    assert result.truncated is True


async def test_archived_sessions_last_page_exactly_at_cap_not_truncated() -> None:
    pages = [
        httpx.Response(200, json={"sessions": [{"id": "s1"}], "cursor": "abc", "hasMore": True}),
        httpx.Response(200, json={"sessions": [{"id": "s2"}], "cursor": "zzz", "hasMore": False}),
    ]
    api = FakeApi({("GET", "/api/sessions/archived"): pages})
    client = make_client(api)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    result = await client.archived_sessions(start=start, end=end, charger_id=CID1, max_pages=2)
    assert [s["id"] for s in result.sessions] == ["s1", "s2"]
    assert result.truncated is False


async def test_archived_sessions_non_dict_body_not_truncated() -> None:
    api = FakeApi({("GET", "/api/sessions/archived"): [httpx.Response(200, json=[])]})
    client = make_client(api)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    assert await client.archived_sessions(start=start, end=end, charger_id=CID1) == (
        [],
        False,
    )
