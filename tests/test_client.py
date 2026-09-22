from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from zaptec_mcp_server.config import ServerConfig
from zaptec_mcp_server.utils.errors import (
    ZaptecApiError,
    ZaptecAuthError,
    ZaptecCommandRejectedError,
    ZaptecConnectionError,
    ZaptecNotFoundError,
    ZaptecPermissionError,
    ZaptecRateLimitError,
)
from zaptec_mcp_server.zaptec.client import ZaptecClient

CFG = ServerConfig.from_env({"ZAPTEC_USERNAME": "u@example.com", "ZAPTEC_PASSWORD": "pw123456"})


class FakeApi:
    """Scripted httpx transport. `script` maps (method, path) -> list of responses.

    The last response of a list is repeated once the queue is exhausted.
    """

    def __init__(self, script: dict[tuple[str, str], list[httpx.Response]]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[httpx.Request] = []
        self.token_calls = 0

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            if request.url.path == "/oauth/token":
                self.token_calls += 1
                body = request.content.decode()
                if "password=wrong" in body:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(
                    200,
                    json={
                        "access_token": f"tok{self.token_calls}",
                        "expires_in": 3600,
                        "token_type": "bearer",
                    },
                )
            key = (request.method, request.url.path)
            queue = self.script.get(key)
            if not queue:
                return httpx.Response(404, json={"detail": "unscripted"})
            return queue.pop(0) if len(queue) > 1 else queue[0]

        return httpx.MockTransport(handler)


def make_client(api: FakeApi, clock: list[float] | None = None) -> ZaptecClient:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    now = clock or [1000.0]
    client = ZaptecClient(CFG, transport=api.transport(), sleep=fake_sleep, clock=lambda: now[0])
    client._test_sleeps = sleeps  # type: ignore[attr-defined]
    return client


def sleeps_of(client: ZaptecClient) -> list[float]:
    return list(client._test_sleeps)  # type: ignore[attr-defined]


async def test_login_once_and_bearer_and_user_agent() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": []})]})
    client = make_client(api)
    await client.request("GET", "/api/chargers")
    await client.request("GET", "/api/chargers")
    assert api.token_calls == 1
    get_calls = [c for c in api.calls if c.url.path == "/api/chargers"]
    assert get_calls[0].headers["Authorization"] == "Bearer tok1"
    assert get_calls[0].headers["User-Agent"].startswith("unofficial-zaptec-mcp/")
    token_call = api.calls[0]
    assert token_call.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "grant_type=password" in token_call.content.decode()
    await client.close()


async def test_token_refreshed_before_expiry() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(200, json={"Data": []})]})
    clock = [1000.0]
    client = make_client(api, clock)
    await client.request("GET", "/api/chargers")
    clock[0] += 3600 - 30  # inside the 60 s margin
    await client.request("GET", "/api/chargers")
    assert api.token_calls == 2


async def test_401_triggers_single_relogin() -> None:
    api = FakeApi(
        {
            ("GET", "/api/chargers"): [
                httpx.Response(401),
                httpx.Response(200, json={"Data": [1]}),
            ]
        }
    )
    client = make_client(api)
    assert await client.request("GET", "/api/chargers") == {"Data": [1]}
    assert api.token_calls == 2


async def test_persistent_401_raises_auth_error() -> None:
    api = FakeApi({("GET", "/api/chargers"): [httpx.Response(401)]})
    client = make_client(api)
    with pytest.raises(ZaptecAuthError):
        await client.request("GET", "/api/chargers")


async def test_bad_credentials_raise_auth_error() -> None:
    cfg = ServerConfig.from_env({"ZAPTEC_USERNAME": "u", "ZAPTEC_PASSWORD": "wrong"})
    api = FakeApi({})
    client = ZaptecClient(cfg, transport=api.transport())
    with pytest.raises(ZaptecAuthError):
        await client.request("GET", "/api/chargers")


async def test_retries_transient_then_succeeds() -> None:
    api = FakeApi(
        {
            ("GET", "/api/x"): [
                httpx.Response(503),
                httpx.Response(502),
                httpx.Response(200, json={"ok": True}),
            ]
        }
    )
    client = make_client(api)
    assert await client.request("GET", "/api/x") == {"ok": True}
    assert len(sleeps_of(client)) == 2


async def test_exhausted_retries_raise_connection_error() -> None:
    api = FakeApi({("GET", "/api/x"): [httpx.Response(503)]})
    client = make_client(api)
    with pytest.raises(ZaptecConnectionError):
        await client.request("GET", "/api/x")
    assert len(sleeps_of(client)) == 3


async def test_429_honors_retry_after_then_raises() -> None:
    api = FakeApi({("GET", "/api/x"): [httpx.Response(429, headers={"Retry-After": "7"})]})
    client = make_client(api)
    with pytest.raises(ZaptecRateLimitError) as info:
        await client.request("GET", "/api/x")
    assert info.value.retry_after_seconds == 7.0
    assert all(s >= 7 for s in sleeps_of(client))


async def test_transport_error_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json=[])

    async def no_sleep(_: float) -> None:
        pass

    client = ZaptecClient(CFG, transport=httpx.MockTransport(handler), sleep=no_sleep)
    assert await client.request("GET", "/api/x") == []
    assert attempts == 2


async def test_500_post_not_retried_and_command_rejection_parsed() -> None:
    api = FakeApi(
        {
            ("POST", "/api/chargers/1/sendCommand/507"): [
                httpx.Response(
                    500, json={"Code": 528, "Details": "Charging is not Paused nor Scheduled"}
                )
            ]
        }
    )
    client = make_client(api)
    with pytest.raises(ZaptecCommandRejectedError) as info:
        await client.request("POST", "/api/chargers/1/sendCommand/507")
    assert info.value.code == 528
    assert "not Paused" in (info.value.details or "")
    assert sleeps_of(client) == []


async def test_500_get_without_code_retried() -> None:
    api = FakeApi(
        {("GET", "/api/x"): [httpx.Response(500, text="oops"), httpx.Response(200, json=1)]}
    )
    client = make_client(api)
    assert await client.request("GET", "/api/x") == 1


async def test_403_404_and_other_errors() -> None:
    api = FakeApi(
        {
            ("GET", "/api/a"): [httpx.Response(403)],
            ("GET", "/api/b"): [httpx.Response(404)],
            ("GET", "/api/c"): [httpx.Response(400, json={"title": "bad"})],
        }
    )
    client = make_client(api)
    with pytest.raises(ZaptecPermissionError):
        await client.request("GET", "/api/a")
    with pytest.raises(ZaptecNotFoundError):
        await client.request("GET", "/api/b")
    with pytest.raises(ZaptecApiError) as info:
        await client.request("GET", "/api/c")
    assert info.value.status == 400


async def test_empty_body_returns_none() -> None:
    api = FakeApi({("POST", "/api/installation/1/update"): [httpx.Response(200)]})
    client = make_client(api)
    assert await client.request("POST", "/api/installation/1/update", json={"a": 1}) is None
    posts = [c for c in api.calls if c.method == "POST" and "update" in c.url.path]
    sent: Any = json.loads(posts[0].content)
    assert sent == {"a": 1}


async def test_login_retries_503_and_429_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/oauth/token":
            attempts += 1
            if attempts == 1:
                return httpx.Response(503)
            if attempts == 2:
                return httpx.Response(429, headers={"Retry-After": "1"})
            return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
        return httpx.Response(200, json=[])

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = ZaptecClient(CFG, transport=httpx.MockTransport(handler), sleep=fake_sleep)
    assert await client.request("GET", "/api/x") == []
    assert attempts == 3
    assert len(sleeps) == 2
    assert sleeps[1] >= 1.0


async def test_login_gives_up_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def no_sleep(_: float) -> None:
        pass

    client = ZaptecClient(CFG, transport=httpx.MockTransport(handler), sleep=no_sleep)
    with pytest.raises(ZaptecConnectionError):
        await client.request("GET", "/api/x")
