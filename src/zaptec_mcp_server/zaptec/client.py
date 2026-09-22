"""Async HTTP client for the Zaptec cloud API.

Owns one httpx.AsyncClient, a cached password-grant token, the retry policy
and thin wrappers around the handful of endpoints this server uses.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from .. import __version__
from ..config import ServerConfig
from ..utils.errors import (
    ZaptecApiError,
    ZaptecAuthError,
    ZaptecCommandRejectedError,
    ZaptecConnectionError,
    ZaptecNotFoundError,
    ZaptecPermissionError,
    ZaptecRateLimitError,
)
from .observations import field

log = logging.getLogger(__name__)

MAX_RETRIES = 3
TOKEN_REFRESH_MARGIN = 60.0
LIST_TTL = 60.0
CMD_PAUSE = 506
CMD_RESUME = 507
REPO_URL = "https://github.com/holger1411/unofficialzaptecMCP"
_BACKOFF_BASE = 0.5
_TRANSIENT_STATUSES = {502, 503, 504}

SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _json_or_none(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _has_code(resp: httpx.Response) -> bool:
    body = _json_or_none(resp)
    return isinstance(body, dict) and "Code" in body


def _data_list(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict):
        data = field(body, "Data") or []
        return [d for d in data if isinstance(d, dict)]
    if isinstance(body, list):
        return [d for d in body if isinstance(d, dict)]
    return []


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ZaptecClient:
    def __init__(
        self,
        cfg: ServerConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn = asyncio.sleep,
        clock: ClockFn = time.monotonic,
    ) -> None:
        self._cfg = cfg
        self._sleep = sleep
        self._clock = clock
        self.user_agent = f"unofficial-zaptec-mcp/{__version__} (+{REPO_URL})"
        self._http = httpx.AsyncClient(
            base_url=cfg.api_base_url,
            timeout=httpx.Timeout(30.0, connect=15.0),
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            transport=transport,
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._login_lock = asyncio.Lock()
        self._chargers_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._installations_cache: tuple[float, list[dict[str, Any]]] | None = None

    async def close(self) -> None:
        await self._http.aclose()

    # -- auth -----------------------------------------------------------------

    def _token_valid(self) -> bool:
        return (
            self._token is not None
            and self._clock() < self._token_expires_at - TOKEN_REFRESH_MARGIN
        )

    async def _ensure_token(self, *, force: bool = False) -> str:
        if not force and self._token_valid() and self._token is not None:
            return self._token
        async with self._login_lock:
            if not force and self._token_valid() and self._token is not None:
                return self._token
            return await self._login()

    async def _login(self) -> str:
        log.info("logging in to Zaptec cloud")
        try:
            resp = await self._http.post(
                "/oauth/token",
                data={
                    "grant_type": "password",
                    "username": self._cfg.username,
                    "password": self._cfg.password,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise ZaptecConnectionError(f"login failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ZaptecAuthError(
                f"login rejected with HTTP {resp.status_code}; "
                "check ZAPTEC_USERNAME and ZAPTEC_PASSWORD"
            )
        body = _json_or_none(resp) or {}
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise ZaptecAuthError("login response contained no access_token")
        expires_in = float(body.get("expires_in") or 3600)
        self._token = token
        self._token_expires_at = self._clock() + expires_in
        return token

    # -- requests -------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        attempt = 0
        reauthed = False
        while True:
            token = await self._ensure_token()
            try:
                resp = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                if attempt < MAX_RETRIES:
                    await self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise ZaptecConnectionError(
                    f"{method} {path} failed after {attempt} retries: {type(exc).__name__}"
                ) from exc

            status = resp.status_code
            if status == 401:
                if reauthed:
                    raise ZaptecAuthError("token rejected twice; check credentials")
                reauthed = True
                await self._ensure_token(force=True)
                continue
            if status == 429:
                wait = _retry_after(resp)
                if attempt < MAX_RETRIES:
                    await self._backoff(attempt, wait)
                    attempt += 1
                    continue
                raise ZaptecRateLimitError(
                    "Zaptec API rate limit exceeded", retry_after_seconds=wait
                )
            retryable_500 = status == 500 and method == "GET" and not _has_code(resp)
            if status in _TRANSIENT_STATUSES or retryable_500:
                if attempt < MAX_RETRIES:
                    await self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise ZaptecConnectionError(
                    f"{method} {path}: HTTP {status} after {attempt} retries"
                )
            if status == 500:
                body = _json_or_none(resp)
                if isinstance(body, dict) and "Code" in body:
                    raise ZaptecCommandRejectedError(
                        f"command rejected: {body.get('Details') or body.get('Code')}",
                        code=body.get("Code"),
                        details=body.get("Details"),
                    )
                raise ZaptecApiError(f"{method} {path}: HTTP 500", status=500, body=resp.text[:500])
            if status == 403:
                raise ZaptecPermissionError(
                    f"{method} {path}: forbidden (owner or service role required)"
                )
            if status == 404:
                raise ZaptecNotFoundError(f"{method} {path}: not found")
            if status >= 400:
                raise ZaptecApiError(
                    f"{method} {path}: HTTP {status}", status=status, body=resp.text[:500]
                )
            if not resp.content:
                return None
            return resp.json()

    async def _backoff(self, attempt: int, retry_after: float | None) -> None:
        delay = _BACKOFF_BASE * (2**attempt) * (1 + random.random() * 0.25)
        if retry_after is not None:
            delay = max(delay, retry_after)
        log.debug("retrying in %.2fs (attempt %d)", delay, attempt + 1)
        await self._sleep(delay)

    # -- endpoints ------------------------------------------------------------

    def invalidate_lists(self) -> None:
        self._chargers_cache = None
        self._installations_cache = None

    async def list_chargers(self) -> list[dict[str, Any]]:
        now = self._clock()
        if self._chargers_cache and self._chargers_cache[0] > now:
            return self._chargers_cache[1]
        body = await self.request("GET", "/api/chargers", params={"PageSize": 100})
        data = _data_list(body)
        self._chargers_cache = (now + LIST_TTL, data)
        return data

    async def list_installations(self) -> list[dict[str, Any]]:
        now = self._clock()
        if self._installations_cache and self._installations_cache[0] > now:
            return self._installations_cache[1]
        body = await self.request("GET", "/api/installation", params={"PageSize": 100})
        data = _data_list(body)
        self._installations_cache = (now + LIST_TTL, data)
        return data

    async def get_charger(self, charger_id: str) -> dict[str, Any]:
        body = await self.request("GET", f"/api/chargers/{charger_id}")
        return body if isinstance(body, dict) else {}

    async def get_charger_state(self, charger_id: str) -> list[dict[str, Any]]:
        body = await self.request("GET", f"/api/chargers/{charger_id}/state")
        return body if isinstance(body, list) else []

    async def get_installation(self, installation_id: str) -> dict[str, Any]:
        body = await self.request("GET", f"/api/installation/{installation_id}")
        return body if isinstance(body, dict) else {}

    async def get_hierarchy(self, installation_id: str) -> dict[str, Any]:
        body = await self.request("GET", f"/api/installation/{installation_id}/hierarchy")
        return body if isinstance(body, dict) else {}

    async def send_command(self, charger_id: str, command_id: int) -> None:
        await self.request("POST", f"/api/chargers/{charger_id}/sendCommand/{command_id}")

    async def update_installation(self, installation_id: str, body: dict[str, Any]) -> None:
        await self.request("POST", f"/api/installation/{installation_id}/update", json=body)

    async def archived_sessions(
        self,
        *,
        start: datetime,
        end: datetime,
        charger_id: str,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "From": _iso_utc(start),
            "To": _iso_utc(end),
            "ChargerId": charger_id,
            "PageSize": 200,
        }
        sessions: list[dict[str, Any]] = []
        for _ in range(max_pages):
            body = await self.request("GET", "/api/sessions/archived", params=params)
            if not isinstance(body, dict):
                break
            page = field(body, "Sessions") or []
            sessions.extend(s for s in page if isinstance(s, dict))
            cursor = field(body, "Cursor")
            if not field(body, "HasMore") or not cursor:
                break
            params = {**params, "Cursor": cursor}
        return sessions

    # -- resolution -----------------------------------------------------------

    async def resolve_charger(self, charger_id: str | None = None) -> dict[str, Any]:
        chargers = await self.list_chargers()
        available = {
            "chargers": [{"id": field(c, "Id"), "name": field(c, "Name")} for c in chargers]
        }
        wanted = charger_id or self._cfg.default_charger_id
        if wanted:
            for c in chargers:
                if field(c, "Id") == wanted:
                    return c
            raise ZaptecNotFoundError(f"charger {wanted!r} not found", available)
        if len(chargers) == 1:
            return chargers[0]
        if not chargers:
            raise ZaptecNotFoundError("no chargers are accessible with this account", available)
        raise ZaptecNotFoundError(
            "several chargers found; pass charger_id or set ZAPTEC_DEFAULT_CHARGER_ID", available
        )

    async def resolve_installation(
        self, installation_id: str | None = None, *, charger: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if installation_id is None:
            if charger is None:
                charger = await self.resolve_charger()
            installation_id = field(charger, "InstallationId")
        if not installation_id:
            raise ZaptecNotFoundError("charger has no installation id")
        return await self.get_installation(installation_id)
