# Unofficial Zaptec MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MCP stdio server that exposes a Zaptec wallbox (status, installation, charge history with optional cost, pause/resume, available current) to Claude Desktop.

**Architecture:** A long-lived `ZaptecClient` (httpx, cached password-grant token, retry/backoff) fetches raw JSON; pure formatter functions turn raw dicts into tool payloads; `ZaptecTools` adds caching and client-side guards; `__main__` registers six MCP tools over stdio. Structure mirrors `holger1411/unofficialMCP4Vaillant`.

**Tech Stack:** Python 3.10–3.14, `mcp>=1.0,<2`, `httpx>=0.27`, pytest + pytest-asyncio, ruff, mypy (strict).

**Spec:** `docs/superpowers/specs/2026-09-22-zaptec-mcp-server-design.md`

## Global Constraints

- Package name `zaptec_mcp_server` under `src/`; distribution name `unofficial-zaptec-mcp`; console script `unofficial-zaptec-mcp`; MCP server name `unofficial-zaptec-mcp`.
- `requires-python = ">=3.10,<3.15"`; dependencies exactly `mcp>=1.0.0,<2` and `httpx>=0.27`.
- All tool names start with `zaptec_`. Tool output is JSON text; errors are raised as `RuntimeError(json.dumps({...}))`.
- Every HTTP request carries `User-Agent: unofficial-zaptec-mcp/<version> (+https://github.com/holger1411/unofficialzaptecMCP)`.
- Never log to stdout (stdout is the MCP transport). Never log the password, tokens, UUIDs or device serials.
- Live API responses use PascalCase keys except `/api/sessions/archived` (camelCase). Use the `field()` helper for case-tolerant access.
- The `pin` value from the user's `.env` is never read.
- `.env` must stay ignored by git; fixtures must be sanitized (no real ids, names, addresses, serials, signatures).
- ruff line length 100; mypy strict on `src`.
- Commit after every task with a conventional message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml` | packaging, ruff, mypy, pytest config |
| `src/zaptec_mcp_server/__init__.py` | `__version__` |
| `src/zaptec_mcp_server/utils/errors.py` | exception hierarchy |
| `src/zaptec_mcp_server/utils/logging.py` | stderr logging + `SecretRedactor` |
| `src/zaptec_mcp_server/cache/manager.py` | `CacheManager` TTL cache |
| `src/zaptec_mcp_server/zaptec/timeranges.py` | `resolve_range` |
| `src/zaptec_mcp_server/config.py` | `ServerConfig.from_env`, `.env` loader |
| `src/zaptec_mcp_server/zaptec/observations.py` | observation table, `StateMap`, enums, `field()`, `parse_api_datetime()` |
| `src/zaptec_mcp_server/zaptec/client.py` | `ZaptecClient` |
| `src/zaptec_mcp_server/zaptec/formatters.py` | `format_status`, `format_installation`, `format_history` |
| `src/zaptec_mcp_server/server.py` | `ZaptecTools` (cache + guards) |
| `src/zaptec_mcp_server/__main__.py` | MCP wiring |
| `scripts/sanitize_fixture.py`, `scripts/probe.py` | fixture capture |
| `tests/…` | unit + integration tests |
| `README.md`, `LICENSE`, `.env.example`, `claude_desktop_config_snippet.json`, `manifest.json`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `.github/…` | deliverables |

---

### Task 1: Scaffold, errors, logging, cache, time ranges

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `src/zaptec_mcp_server/__init__.py`, `src/zaptec_mcp_server/utils/__init__.py`, `src/zaptec_mcp_server/utils/errors.py`, `src/zaptec_mcp_server/utils/logging.py`, `src/zaptec_mcp_server/cache/__init__.py`, `src/zaptec_mcp_server/cache/manager.py`, `src/zaptec_mcp_server/zaptec/__init__.py`, `src/zaptec_mcp_server/zaptec/timeranges.py`
- Test: `tests/__init__.py`, `tests/test_errors.py`, `tests/test_logging.py`, `tests/test_cache.py`, `tests/test_timeranges.py`

**Interfaces:**
- Produces: `ZaptecError(message, payload=None)` with `.payload: dict`; subclasses `ZaptecAuthError`, `ZaptecPermissionError`, `ZaptecNotFoundError(message, available=None)`, `ZaptecConnectionError`, `ZaptecRateLimitError(message, retry_after_seconds=None)`, `ZaptecApiError(message, status=None, body=None)`, `ZaptecCommandRejectedError(message, code=None, details=None)`, `ZaptecGuardError(message, payload=None)`.
- `configure_logging(level: str) -> SecretRedactor`; `SecretRedactor.add(secret)`.
- `CacheManager(enabled=True).get_or_load(tool, args, ttl, loader)`, `.clear()`, `.invalidate(tool)`.
- `resolve_range(name, *, now, tz, start_date=None, end_date=None) -> tuple[datetime, datetime]`.

- [ ] **Step 1: Create venv and pyproject**

```bash
cd /Users/holgerkonemann/Developer/unofficialzaptecMCP
python3 -m venv .venv && source .venv/bin/activate && pip install -q --upgrade pip
```

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "unofficial-zaptec-mcp"
version = "0.1.0"
description = "Unofficial MCP server for Zaptec EV chargers (status, history, pause/resume, available current). Not affiliated with Zaptec AS."
readme = "README.md"
requires-python = ">=3.10,<3.15"
license = { text = "MIT" }
authors = [{ name = "Holger Koenemann" }]
keywords = ["mcp", "zaptec", "ev-charger", "wallbox", "home-automation", "claude"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Programming Language :: Python :: 3.14",
  "Topic :: Home Automation",
]
dependencies = [
  "mcp>=1.0.0,<2",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
  "pytest>=7",
  "pytest-asyncio>=0.23",
  "pytest-cov",
  "ruff>=0.5",
  "mypy>=1.8",
]

[project.scripts]
unofficial-zaptec-mcp = "zaptec_mcp_server.__main__:main"

[project.urls]
Homepage = "https://github.com/holger1411/unofficialzaptecMCP"
Issues = "https://github.com/holger1411/unofficialzaptecMCP/issues"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "RUF"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.10"
strict = true
ignore_missing_imports = true
files = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]
markers = [
  "integration: live API tests, requires .env, opt in via -m integration",
]
addopts = "-q --strict-markers"
```

`LICENSE`: MIT text with `Copyright (c) 2026 Holger Koenemann`.

`src/zaptec_mcp_server/__init__.py`:

```python
"""Unofficial MCP server for Zaptec EV chargers."""

__version__ = "0.1.0"
```

Empty `__init__.py` in `utils/`, `cache/`, `zaptec/`, `tests/`. Also create an empty `README.md` placeholder line `# unofficialzaptecMCP` so `pip install -e .` works (filled in Task 10).

- [ ] **Step 2: Write failing tests for errors, logging, cache, timeranges**

`tests/test_errors.py`:

```python
from zaptec_mcp_server.utils.errors import (
    ZaptecApiError,
    ZaptecCommandRejectedError,
    ZaptecError,
    ZaptecGuardError,
    ZaptecNotFoundError,
    ZaptecRateLimitError,
)


def test_base_error_has_payload() -> None:
    err = ZaptecError("boom", {"a": 1})
    assert str(err) == "boom"
    assert err.payload == {"a": 1}
    assert ZaptecError("x").payload == {}


def test_rate_limit_carries_retry_after() -> None:
    err = ZaptecRateLimitError("slow down", retry_after_seconds=2.5)
    assert err.retry_after_seconds == 2.5
    assert err.payload["retry_after_seconds"] == 2.5


def test_not_found_payload_lists_available() -> None:
    err = ZaptecNotFoundError("no charger", available={"chargers": ["a"]})
    assert err.payload == {"chargers": ["a"]}


def test_api_error_payload() -> None:
    err = ZaptecApiError("bad", status=418, body="teapot")
    assert err.payload == {"status": 418, "body": "teapot"}


def test_command_rejected_payload() -> None:
    err = ZaptecCommandRejectedError("nope", code=528, details="not paused")
    assert err.payload == {"code": 528, "details": "not paused"}
    assert isinstance(err, ZaptecError)


def test_guard_error_is_zaptec_error() -> None:
    assert isinstance(ZaptecGuardError("wait", {"seconds_until_allowed": 3}), ZaptecError)
```

`tests/test_logging.py`:

```python
import logging

from zaptec_mcp_server.utils.logging import REDACTED, SecretRedactor, configure_logging


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def test_redacts_registered_secret() -> None:
    r = SecretRedactor()
    r.add("hunter22")
    rec = _record("password=hunter22 ok")
    r.filter(rec)
    assert rec.getMessage() == f"password={REDACTED} ok"


def test_short_secret_ignored() -> None:
    r = SecretRedactor()
    r.add("abc")
    rec = _record("abc")
    r.filter(rec)
    assert rec.getMessage() == "abc"


def test_redacts_uuid_serial_and_bearer() -> None:
    r = SecretRedactor()
    rec = _record(
        "id=1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d dev=ZAP123456 Authorization: Bearer eyJabc.def"
    )
    r.filter(rec)
    msg = rec.getMessage()
    assert "1a2b3c4d" not in msg
    assert "ZAP123456" not in msg
    assert "eyJabc" not in msg
    assert msg.count(REDACTED) == 3


def test_configure_logging_uses_stderr(capsys) -> None:  # type: ignore[no-untyped-def]
    redactor = configure_logging("DEBUG")
    redactor.add("secretvalue")
    logging.getLogger("x").info("token secretvalue")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert REDACTED in captured.err
```

`tests/test_cache.py`:

```python
import pytest

from zaptec_mcp_server.cache.manager import CacheManager


async def test_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager()
    assert await cache.get_or_load("t", {"a": 1}, ttl=60, loader=loader) == 1
    assert await cache.get_or_load("t", {"a": 1}, ttl=60, loader=loader) == 1
    assert await cache.get_or_load("t", {"a": 2}, ttl=60, loader=loader) == 2


async def test_ttl_zero_or_disabled_bypasses() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager()
    assert await cache.get_or_load("t", {}, ttl=0, loader=loader) == 1
    assert await cache.get_or_load("t", {}, ttl=0, loader=loader) == 2
    off = CacheManager(enabled=False)
    assert await off.get_or_load("t", {}, ttl=60, loader=loader) == 3
    assert await off.get_or_load("t", {}, ttl=60, loader=loader) == 4


async def test_failures_not_cached() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("fail")
        return calls

    cache = CacheManager()
    with pytest.raises(RuntimeError):
        await cache.get_or_load("t", {}, ttl=60, loader=loader)
    assert await cache.get_or_load("t", {}, ttl=60, loader=loader) == 2


async def test_invalidate_by_tool() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    cache = CacheManager()
    await cache.get_or_load("status", {"c": "1"}, ttl=60, loader=loader)
    await cache.get_or_load("other", {}, ttl=60, loader=loader)
    cache.invalidate("status")
    assert await cache.get_or_load("status", {"c": "1"}, ttl=60, loader=loader) == 3
    assert await cache.get_or_load("other", {}, ttl=60, loader=loader) == 2
```

`tests/test_timeranges.py`:

```python
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from zaptec_mcp_server.zaptec.timeranges import resolve_range

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)  # Tuesday, 16:30 Berlin


def test_today() -> None:
    start, end = resolve_range("today", now=NOW, tz=TZ)
    assert start == datetime(2026, 9, 22, 0, 0, tzinfo=TZ)
    assert end == NOW.astimezone(TZ)


def test_yesterday_is_whole_day() -> None:
    start, end = resolve_range("yesterday", now=NOW, tz=TZ)
    assert start == datetime(2026, 9, 21, tzinfo=TZ)
    assert end == datetime(2026, 9, 22, tzinfo=TZ)


def test_week_starts_monday() -> None:
    start, _ = resolve_range("week", now=NOW, tz=TZ)
    assert start == datetime(2026, 9, 21, tzinfo=TZ)


def test_month_and_year() -> None:
    assert resolve_range("month", now=NOW, tz=TZ)[0] == datetime(2026, 9, 1, tzinfo=TZ)
    assert resolve_range("year", now=NOW, tz=TZ)[0] == datetime(2026, 1, 1, tzinfo=TZ)


def test_custom_end_exclusive() -> None:
    start, end = resolve_range(
        "custom", now=NOW, tz=TZ, start_date=date(2026, 9, 1), end_date=date(2026, 9, 3)
    )
    assert start == datetime(2026, 9, 1, tzinfo=TZ)
    assert end == datetime(2026, 9, 4, tzinfo=TZ)


def test_custom_requires_dates_and_unknown_raises() -> None:
    with pytest.raises(ValueError):
        resolve_range("custom", now=NOW, tz=TZ)
    with pytest.raises(ValueError):
        resolve_range("decade", now=NOW, tz=TZ)
    with pytest.raises(ValueError):
        resolve_range("today", now=NOW.replace(tzinfo=None), tz=TZ)
```

- [ ] **Step 3: Run tests, expect ImportError**

Run: `pip install -e '.[dev]' && pytest tests/test_errors.py tests/test_logging.py tests/test_cache.py tests/test_timeranges.py -q`
Expected: collection errors (modules missing).

- [ ] **Step 4: Implement the four modules**

`src/zaptec_mcp_server/utils/errors.py`:

```python
"""Exception hierarchy for zaptec_mcp_server.

Tools raise these; `__main__` turns them into structured MCP errors.
"""

from __future__ import annotations

from typing import Any


class ZaptecError(Exception):
    """Base class. `payload` is merged into the structured error sent to the client."""

    def __init__(self, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload: dict[str, Any] = payload or {}


class ZaptecAuthError(ZaptecError):
    """Login failed (bad credentials, token rejected twice)."""


class ZaptecPermissionError(ZaptecError):
    """HTTP 403: the account lacks owner/service rights for this call."""


class ZaptecNotFoundError(ZaptecError):
    """Unknown charger/installation id. Payload lists what is available."""

    def __init__(self, message: str, available: dict[str, Any] | None = None) -> None:
        super().__init__(message, payload=available)


class ZaptecConnectionError(ZaptecError):
    """Network / timeout / 5xx after retries."""


class ZaptecRateLimitError(ZaptecError):
    """HTTP 429 after retries."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message, {"retry_after_seconds": retry_after_seconds})
        self.retry_after_seconds = retry_after_seconds


class ZaptecApiError(ZaptecError):
    """Any other non-success HTTP response."""

    def __init__(self, message: str, status: int | None = None, body: str | None = None) -> None:
        super().__init__(message, {"status": status, "body": body})
        self.status = status
        self.body = body


class ZaptecCommandRejectedError(ZaptecError):
    """The charger/cloud rejected a command (HTTP 500 with a `Code`)."""

    def __init__(self, message: str, code: int | None = None, details: str | None = None) -> None:
        super().__init__(message, {"code": code, "details": details})
        self.code = code
        self.details = details


class ZaptecGuardError(ZaptecError):
    """A client-side precondition (state check, rate guard, validation) failed."""
```

`src/zaptec_mcp_server/utils/logging.py` — copy of the Vaillant module with these changes: serial pattern `\bGPN\d{6,}\b|\bZPR\d{6,}\b` replaced by a generic Zaptec device-id pattern `\b[A-Z]{3}\d{6,}\b`, plus a bearer-token pattern `Bearer\s+[A-Za-z0-9._-]{8,}` → `Bearer ***REDACTED***` (count that as one redaction: replace the whole `Bearer xxx` with `Bearer ` + REDACTED). Full module:

```python
"""Stderr logging with a runtime secret redactor.

MCP servers use stdout for JSON-RPC, so all logs MUST go to stderr. The
redactor scrubs registered secrets (password, tokens) and anything shaped
like a UUID, a Zaptec device id (three letters + digits) or a bearer token.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Final

REDACTED: Final[str] = "***REDACTED***"

_DEVICE_ID_PATTERN = re.compile(r"\b[A-Z]{3}\d{6,}\b")
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}")
_MIN_SECRET_LEN = 6


class SecretRedactor(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def add(self, secret: str | None) -> None:
        if not secret or len(secret) < _MIN_SECRET_LEN:
            return
        self._secrets.add(secret)

    def scrub(self, text: str) -> str:
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        text = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)
        text = _UUID_PATTERN.sub(REDACTED, text)
        text = _DEVICE_ID_PATTERN.sub(REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.scrub(record.getMessage())
        record.args = None
        return True


def configure_logging(level: str = "INFO") -> SecretRedactor:
    redactor = SecretRedactor()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(redactor)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    return redactor
```

`src/zaptec_mcp_server/cache/manager.py` — copy of the Vaillant module plus:

```python
    def invalidate(self, tool: str) -> None:
        """Drop every cached entry for one tool."""
        for key in [k for k in self._store if isinstance(k, tuple) and k[0] == tool]:
            del self._store[key]
```

`src/zaptec_mcp_server/zaptec/timeranges.py` — verbatim copy of the Vaillant module (docstring: "in the installation's timezone").

- [ ] **Step 5: Run tests, lint, type-check**

Run: `pytest tests/test_errors.py tests/test_logging.py tests/test_cache.py tests/test_timeranges.py -q && ruff check . && mypy`
Expected: all pass, no lint or type errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml LICENSE README.md src tests
git commit -m "feat: scaffold package with errors, logging, cache and time ranges"
```

---

### Task 2: Config and `.env` loading

**Files:**
- Create: `src/zaptec_mcp_server/config.py`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ServerConfig` frozen dataclass with fields `username: str`, `password: str`, `price_per_kwh: float | None`, `currency: str`, `default_charger_id: str | None`, `min_current_update_interval: float`, `cache_enabled: bool`, `log_level: str`, `api_base_url: str`; `ServerConfig.from_env(env: Mapping[str, str] | None = None) -> ServerConfig`; `load_dotenv(path: Path = Path(".env")) -> dict[str, str]` (parses and injects into `os.environ` without overriding existing keys).

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`:

```python
import os
from pathlib import Path

import pytest

from zaptec_mcp_server.config import ServerConfig, load_dotenv
from zaptec_mcp_server.utils.errors import ZaptecAuthError

BASE = {"ZAPTEC_USERNAME": "me@example.com", "ZAPTEC_PASSWORD": "secret-pw"}


def test_defaults() -> None:
    cfg = ServerConfig.from_env(BASE)
    assert cfg.username == "me@example.com"
    assert cfg.price_per_kwh is None
    assert cfg.currency == "EUR"
    assert cfg.default_charger_id is None
    assert cfg.min_current_update_interval == 900.0
    assert cfg.cache_enabled is True
    assert cfg.log_level == "INFO"
    assert cfg.api_base_url == "https://api.zaptec.com"


def test_missing_credentials_raise() -> None:
    with pytest.raises(ZaptecAuthError):
        ServerConfig.from_env({"ZAPTEC_USERNAME": "x"})


def test_overrides_and_parsing() -> None:
    cfg = ServerConfig.from_env(
        {
            **BASE,
            "ZAPTEC_PRICE_PER_KWH": "0,35",
            "ZAPTEC_CURRENCY": "chf",
            "ZAPTEC_DEFAULT_CHARGER_ID": " abc ",
            "ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL": "0",
            "ZAPTEC_CACHE_ENABLED": "no",
            "ZAPTEC_LOG_LEVEL": "debug",
            "ZAPTEC_API_BASE_URL": "http://localhost:9999/",
        }
    )
    assert cfg.price_per_kwh == 0.35
    assert cfg.currency == "CHF"
    assert cfg.default_charger_id == "abc"
    assert cfg.min_current_update_interval == 0.0
    assert cfg.cache_enabled is False
    assert cfg.log_level == "DEBUG"
    assert cfg.api_base_url == "http://localhost:9999"


def test_invalid_price_raises() -> None:
    with pytest.raises(ValueError):
        ServerConfig.from_env({**BASE, "ZAPTEC_PRICE_PER_KWH": "cheap"})
    with pytest.raises(ValueError):
        ServerConfig.from_env({**BASE, "ZAPTEC_PRICE_PER_KWH": "-1"})


def test_load_dotenv_does_not_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nZAPTEC_USERNAME="file@example.com"\nZAPTEC_PASSWORD=pw\n'
        "export ZAPTEC_CURRENCY=NOK\npin=1234\ninvalid line\n"
    )
    monkeypatch.setenv("ZAPTEC_USERNAME", "env@example.com")
    monkeypatch.delenv("ZAPTEC_PASSWORD", raising=False)
    monkeypatch.delenv("ZAPTEC_CURRENCY", raising=False)
    parsed = load_dotenv(env_file)
    assert parsed["ZAPTEC_USERNAME"] == "file@example.com"
    assert os.environ["ZAPTEC_USERNAME"] == "env@example.com"
    assert os.environ["ZAPTEC_PASSWORD"] == "pw"
    assert os.environ["ZAPTEC_CURRENCY"] == "NOK"
    assert "pin" in parsed


def test_load_dotenv_missing_file(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "nope") == {}
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_config.py -q` → ImportError.

- [ ] **Step 3: Implement**

`src/zaptec_mcp_server/config.py`:

```python
"""Environment-variable driven configuration (+ minimal .env loader)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .utils.errors import ZaptecAuthError

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}
DEFAULT_BASE_URL = "https://api.zaptec.com"


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def _float(raw: str | None, name: str) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    """Parse KEY=VALUE lines; inject into os.environ without overriding."""
    if not path.is_file():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        parsed[key] = value
        os.environ.setdefault(key, value)
    return parsed


@dataclass(frozen=True)
class ServerConfig:
    username: str
    password: str
    price_per_kwh: float | None
    currency: str
    default_charger_id: str | None
    min_current_update_interval: float
    cache_enabled: bool
    log_level: str
    api_base_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServerConfig:
        e = os.environ if env is None else env
        username = e.get("ZAPTEC_USERNAME", "").strip()
        password = e.get("ZAPTEC_PASSWORD", "").strip()
        if not username or not password:
            raise ZaptecAuthError("ZAPTEC_USERNAME and ZAPTEC_PASSWORD are required")
        interval = _float(e.get("ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL"), "ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL")
        return cls(
            username=username,
            password=password,
            price_per_kwh=_float(e.get("ZAPTEC_PRICE_PER_KWH"), "ZAPTEC_PRICE_PER_KWH"),
            currency=(e.get("ZAPTEC_CURRENCY") or "EUR").strip().upper(),
            default_charger_id=e.get("ZAPTEC_DEFAULT_CHARGER_ID", "").strip() or None,
            min_current_update_interval=900.0 if interval is None else interval,
            cache_enabled=_bool(e.get("ZAPTEC_CACHE_ENABLED"), True),
            log_level=(e.get("ZAPTEC_LOG_LEVEL") or "INFO").strip().upper(),
            api_base_url=(e.get("ZAPTEC_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
        )
```

`.env.example`:

```
# Zaptec portal / app login (same as the Zaptec app)
ZAPTEC_USERNAME=your-email@example.com
ZAPTEC_PASSWORD=your-password

# Optional: enables cost fields in zaptec_get_charge_history
#ZAPTEC_PRICE_PER_KWH=0.30
#ZAPTEC_CURRENCY=EUR

# Optional: only needed when the account has more than one charger
#ZAPTEC_DEFAULT_CHARGER_ID=

# Guard between two available-current changes (seconds, 0 disables)
#ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL=900

#ZAPTEC_CACHE_ENABLED=true
#ZAPTEC_LOG_LEVEL=INFO
```

- [ ] **Step 4: Run tests, lint, mypy** → pass.

- [ ] **Step 5: Commit** `git add src/zaptec_mcp_server/config.py .env.example tests/test_config.py && git commit -m "feat: config from environment with .env loader"`

---

### Task 3: Observations, enums, field helper, datetime parser

**Files:**
- Create: `src/zaptec_mcp_server/zaptec/observations.py`
- Test: `tests/test_observations.py`

**Interfaces:**
- Produces: `OBSERVATIONS: dict[int, str]`; `Obs` class with int constants (`AUTHENTICATION_REQUIRED=120, COMMUNICATION_MODE=150, PERMANENT_CABLE_LOCK=151, TEMPERATURE_INTERNAL=201, HUMIDITY=270, VOLTAGE_L1=501, VOLTAGE_L2=502, VOLTAGE_L3=503, CURRENT_L1=507, CURRENT_L2=508, CURRENT_L3=509, CHARGER_MAX_CURRENT=510, CHARGER_MIN_CURRENT=511, TOTAL_CHARGE_POWER=513, ACTIVE_PHASES=519, MAX_PHASES=520, SESSION_ENERGY=553, SIGNED_METER_VALUE=554, CHARGE_MODE=702, CHARGE_CURRENT_SET=708, OPERATION_MODE=710, IS_ENABLED=711, CABLE_TYPE=714, FINAL_STOP_ACTIVE=718, SESSION_IDENTIFIER=721, NEXT_SCHEDULE_EVENT=763, WARNINGS=804, SIGNAL_STRENGTH=809, CLOUD_CONNECTION=810, UPTIME=820`).
- `OPERATING_MODES: dict[int, str]`, `MODE_HINTS: dict[int, str]`, `DEVICE_TYPES: dict[int, str]`, `NETWORK_TYPES: dict[int, str]`, `AVAILABLE_CURRENT_MODES: dict[int, str]`, `FEATURES: dict[int, str]`, `decode_features(bits: int | None) -> list[str]`, `decode_phases(bits: int | None) -> list[str]`.
- `StateMap(entries: list[dict])` with `.get(id) -> str | None`, `.get_float(id) -> float | None`, `.get_int(id) -> int | None`, `.get_bool(id) -> bool | None`, `.timestamp(id) -> str | None`, `.newest_timestamp() -> str | None`, `.ids() -> list[int]`.
- `field(d: Mapping, name: str, default=None)` case-tolerant getter (`name`, then `name[0].lower()+name[1:]`, then case-insensitive scan).
- `parse_api_datetime(value: str | None) -> datetime | None` (aware, UTC when naive; tolerant of 1–7 fraction digits, `Z`, `+00:00`).
- `parse_ocmf(value: str | None) -> dict[str, Any]` returns the first JSON block of an `OCMF|{...}|{...}` string or `{}`.

- [ ] **Step 1: Write failing tests**

`tests/test_observations.py`:

```python
from datetime import datetime, timezone

from zaptec_mcp_server.zaptec.observations import (
    OBSERVATIONS,
    OPERATING_MODES,
    Obs,
    StateMap,
    decode_features,
    decode_phases,
    field,
    parse_api_datetime,
    parse_ocmf,
)


def test_observation_table_sample() -> None:
    assert OBSERVATIONS[710] == "ChargerOperationMode"
    assert OBSERVATIONS[513] == "TotalChargePower"
    assert OBSERVATIONS[718] == "FinalStopActive"
    assert Obs.OPERATION_MODE == 710
    assert OPERATING_MODES[5] == "connected_finished"


def test_state_map_accessors() -> None:
    sm = StateMap(
        [
            {"StateId": 710, "ValueAsString": "3", "Timestamp": "2026-09-22T14:17:42.1"},
            {"StateId": 513, "ValueAsString": "17.062", "Timestamp": "2026-09-22T14:30:18.5"},
            {"StateId": 718, "ValueAsString": "0", "Timestamp": "2026-09-21T07:15:02"},
            {"StateId": 150, "ValueAsString": "Wifi", "Timestamp": None},
        ]
    )
    assert sm.get_int(710) == 3
    assert sm.get_float(513) == 17.062
    assert sm.get_bool(718) is False
    assert sm.get(150) == "Wifi"
    assert sm.get(999) is None
    assert sm.get_float(150) is None
    assert sm.timestamp(710) == "2026-09-22T14:17:42.1"
    assert sm.newest_timestamp() == "2026-09-22T14:30:18.5"
    assert sm.ids() == [150, 513, 710, 718]


def test_field_is_case_tolerant() -> None:
    assert field({"OperatingMode": 3}, "OperatingMode") == 3
    assert field({"operatingMode": 3}, "OperatingMode") == 3
    assert field({"operatingmode": 3}, "OperatingMode") == 3
    assert field({}, "OperatingMode", "x") == "x"


def test_parse_api_datetime_variants() -> None:
    assert parse_api_datetime("2026-09-20T11:11:06.77+00:00") == datetime(
        2026, 9, 20, 11, 11, 6, 770000, tzinfo=timezone.utc
    )
    assert parse_api_datetime("2026-09-21T10:48:43.91") == datetime(
        2026, 9, 21, 10, 48, 43, 910000, tzinfo=timezone.utc
    )
    assert parse_api_datetime("2026-09-21T10:48:43Z") == datetime(
        2026, 9, 21, 10, 48, 43, tzinfo=timezone.utc
    )
    assert parse_api_datetime("2026-09-21T10:48:43.1234567") == datetime(
        2026, 9, 21, 10, 48, 43, 123456, tzinfo=timezone.utc
    )
    assert parse_api_datetime(None) is None
    assert parse_api_datetime("garbage") is None


def test_decoders() -> None:
    assert decode_features(0) == []
    assert decode_features(131543) == [
        "Api_MessageSubscription",
        "Authentication_Internal",
        "PowerManagement_Apm",
        "PowerManagement_Schedule",
        "PowerManagement_Apm_PowerLimit",
        "Connectivity_4G",
        "Authentication_Ocpp",
        "PowerManagement_Apm_Tic",
        "PowerManagement_Apm_SurplusMode",
    ]
    assert decode_features(None) == []
    assert decode_phases(4) == ["L3"]
    assert decode_phases(7) == ["L1", "L2", "L3"]
    assert decode_phases(0) == []


def test_parse_ocmf() -> None:
    raw = 'OCMF|{"FV":"1.0","GI":"Zaptec Go 2","GS":"ZPR000001","GV":"3.1.0.8"}|{"SA":"x"}'
    assert parse_ocmf(raw)["GV"] == "3.1.0.8"
    assert parse_ocmf("nonsense") == {}
    assert parse_ocmf(None) == {}
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement**

`src/zaptec_mcp_server/zaptec/observations.py` — the `OBSERVATIONS` table is generated once from the OpenAPI enum with this snippet and pasted as a literal:

```bash
python3 - <<'EOF'
import json,re
d=json.load(open('apidocs/ZaptecApi.json'))
desc=d['components']['schemas']['ObservationId']['description']
pairs=re.findall(r"(\d+) = (\w+)",desc)
print("OBSERVATIONS: dict[int, str] = {")
for k,v in pairs: print(f"    {k}: \"{v}\",")
print("}")
EOF
```

Module:

```python
"""Observation-id table, enum decoders and small parsing helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

OBSERVATIONS: dict[int, str] = {
    # ... pasted from the snippet above (0 Unknown ... 856 EnableLteDetailedSignalStrength)
}


class Obs:
    AUTHENTICATION_REQUIRED = 120
    COMMUNICATION_MODE = 150
    PERMANENT_CABLE_LOCK = 151
    TEMPERATURE_INTERNAL = 201
    HUMIDITY = 270
    VOLTAGE_L1 = 501
    VOLTAGE_L2 = 502
    VOLTAGE_L3 = 503
    CURRENT_L1 = 507
    CURRENT_L2 = 508
    CURRENT_L3 = 509
    CHARGER_MAX_CURRENT = 510
    CHARGER_MIN_CURRENT = 511
    TOTAL_CHARGE_POWER = 513
    ACTIVE_PHASES = 519
    MAX_PHASES = 520
    SESSION_ENERGY = 553
    SIGNED_METER_VALUE = 554
    CHARGE_MODE = 702
    CHARGE_CURRENT_SET = 708
    OPERATION_MODE = 710
    IS_ENABLED = 711
    CABLE_TYPE = 714
    FINAL_STOP_ACTIVE = 718
    SESSION_IDENTIFIER = 721
    NEXT_SCHEDULE_EVENT = 763
    WARNINGS = 804
    SIGNAL_STRENGTH = 809
    CLOUD_CONNECTION = 810
    UPTIME = 820


OPERATING_MODES: dict[int, str] = {
    0: "unknown",
    1: "disconnected",
    2: "connected_requesting",
    3: "connected_charging",
    5: "connected_finished",
}
MODE_HINTS: dict[int, str] = {
    0: "state unknown (charger offline or no data yet)",
    1: "no vehicle connected",
    2: "vehicle connected, waiting for authorization or for the vehicle to request power",
    3: "charging",
    5: "connected but not charging: paused by user/app, finished, or vehicle stopped drawing",
}
DEVICE_TYPES: dict[int, str] = {
    0: "Unknown",
    1: "Zaptec Pro",
    2: "Zaptec Portable",
    3: "Zaptec Home APM",
    4: "Zaptec Go",
    5: "Other APM",
    6: "Generic APM",
    7: "HAN APM",
    8: "TIC APM",
}
NETWORK_TYPES: dict[int, str] = {
    0: "unknown",
    1: "IT_1_phase",
    2: "IT_3_phase",
    3: "TN_1_phase",
    4: "TN_3_phase",
}
AVAILABLE_CURRENT_MODES: dict[int, str] = {0: "manual", 1: "schedule", 2: "auto"}
FEATURES: dict[int, str] = {
    1: "Api_MessageSubscription",
    2: "Authentication_Internal",
    4: "PowerManagement_Apm",
    8: "PowerManagement_EcoMode",
    16: "PowerManagement_Schedule",
    32: "PowerManagement_Apm_PowerLimit",
    64: "Connectivity_4G",
    128: "Authentication_Ocpp",
    256: "PowerManagement_Apm_Tariff_PowerLimit",
    512: "Authentication_OcppNative",
    65536: "PowerManagement_Apm_Tic",
    131072: "PowerManagement_Apm_SurplusMode",
}
_PHASE_BITS = {1: "L1", 2: "L2", 4: "L3"}


def decode_features(bits: int | None) -> list[str]:
    if not bits:
        return []
    return [name for bit, name in FEATURES.items() if bits & bit]


def decode_phases(bits: int | None) -> list[str]:
    if not bits:
        return []
    return [name for bit, name in _PHASE_BITS.items() if bits & bit]


def field(d: Mapping[str, Any], name: str, default: Any = None) -> Any:
    """Case-tolerant key lookup: exact, camelCase, then case-insensitive."""
    if name in d:
        return d[name]
    camel = name[:1].lower() + name[1:]
    if camel in d:
        return d[camel]
    lowered = name.lower()
    for key, value in d.items():
        if key.lower() == lowered:
            return value
    return default


_FRACTION = re.compile(r"(\.\d+)")


def parse_api_datetime(value: str | None) -> datetime | None:
    """Parse Zaptec timestamps (naive = UTC, any fraction length, Z or offset)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")

    def _pad(m: re.Match[str]) -> str:
        digits = m.group(1)[1:][:6]
        return "." + digits.ljust(6, "0")

    text = _FRACTION.sub(_pad, text, count=1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_ocmf(value: str | None) -> dict[str, Any]:
    if not value or not value.startswith("OCMF|"):
        return {}
    parts = value.split("|")
    if len(parts) < 2:
        return {}
    try:
        data = json.loads(parts[1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class StateMap:
    """Index a `/api/chargers/{id}/state` list by observation id."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._by_id: dict[int, dict[str, Any]] = {}
        for entry in entries:
            sid = field(entry, "StateId")
            if isinstance(sid, int):
                self._by_id[sid] = entry

    def ids(self) -> list[int]:
        return sorted(self._by_id)

    def get(self, sid: int) -> str | None:
        entry = self._by_id.get(sid)
        if entry is None:
            return None
        value = field(entry, "ValueAsString")
        return None if value is None else str(value)

    def get_float(self, sid: int) -> float | None:
        raw = self.get(sid)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def get_int(self, sid: int) -> int | None:
        value = self.get_float(sid)
        return None if value is None else int(value)

    def get_bool(self, sid: int) -> bool | None:
        value = self.get_int(sid)
        return None if value is None else value != 0

    def timestamp(self, sid: int) -> str | None:
        entry = self._by_id.get(sid)
        if entry is None:
            return None
        ts = field(entry, "Timestamp")
        return None if ts is None else str(ts)

    def newest_timestamp(self) -> str | None:
        stamps = [field(e, "Timestamp") for e in self._by_id.values()]
        valid = [s for s in stamps if isinstance(s, str)]
        return max(valid) if valid else None
```

- [ ] **Step 4: Run tests, ruff, mypy** → pass.

- [ ] **Step 5: Commit** `git commit -am "feat: observation table, enum decoders and parsing helpers"` (add the new files first).

---

### Task 4: ZaptecClient — auth, request, retry

**Files:**
- Create: `src/zaptec_mcp_server/zaptec/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `ServerConfig`, errors from Task 1, `__version__`.
- Produces: `ZaptecClient(cfg, *, transport: httpx.AsyncBaseTransport | None = None, sleep=asyncio.sleep, clock=time.monotonic)`; `await client.request(method, path, *, params=None, json=None) -> Any`; `await client.close()`; `client.user_agent: str`; constants `MAX_RETRIES = 3`, `TOKEN_REFRESH_MARGIN = 60.0`.

- [ ] **Step 1: Write failing tests**

`tests/test_client.py`:

```python
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
    """Scripted httpx transport. `script` maps (method, path) -> list of responses."""

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
    assert len(client._test_sleeps) == 2  # type: ignore[attr-defined]


async def test_exhausted_retries_raise_connection_error() -> None:
    api = FakeApi({("GET", "/api/x"): [httpx.Response(503)]})
    client = make_client(api)
    with pytest.raises(ZaptecConnectionError):
        await client.request("GET", "/api/x")
    assert len(client._test_sleeps) == 3  # type: ignore[attr-defined]


async def test_429_honors_retry_after_then_raises() -> None:
    api = FakeApi({("GET", "/api/x"): [httpx.Response(429, headers={"Retry-After": "7"})]})
    client = make_client(api)
    with pytest.raises(ZaptecRateLimitError) as info:
        await client.request("GET", "/api/x")
    assert info.value.retry_after_seconds == 7.0
    assert all(s >= 7 for s in client._test_sleeps)  # type: ignore[attr-defined]


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
                httpx.Response(500, json={"Code": 528, "Details": "Charging is not Paused nor Scheduled"})
            ]
        }
    )
    client = make_client(api)
    with pytest.raises(ZaptecCommandRejectedError) as info:
        await client.request("POST", "/api/chargers/1/sendCommand/507")
    assert info.value.code == 528
    assert "not Paused" in (info.value.details or "")
    assert client._test_sleeps == []  # type: ignore[attr-defined]


async def test_500_get_without_code_retried() -> None:
    api = FakeApi({("GET", "/api/x"): [httpx.Response(500, text="oops"), httpx.Response(200, json=1)]})
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
    sent: Any = json.loads([c for c in api.calls if c.method == "POST" and "update" in c.url.path][0].content)
    assert sent == {"a": 1}
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement**

`src/zaptec_mcp_server/zaptec/client.py`:

```python
"""Async HTTP client for the Zaptec cloud API.

Owns one httpx.AsyncClient, a cached password-grant token and the retry policy.
Endpoint wrappers (Task 5) live further down in this module.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
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

log = logging.getLogger(__name__)

MAX_RETRIES = 3
TOKEN_REFRESH_MARGIN = 60.0
_BACKOFF_BASE = 0.5
_TRANSIENT_STATUSES = {502, 503, 504}
REPO_URL = "https://github.com/holger1411/unofficialzaptecMCP"

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

    async def close(self) -> None:
        await self._http.aclose()

    # -- auth -----------------------------------------------------------------

    def _token_valid(self) -> bool:
        return self._token is not None and self._clock() < self._token_expires_at - TOKEN_REFRESH_MARGIN

    async def _ensure_token(self, *, force: bool = False) -> str:
        if not force and self._token_valid():
            assert self._token is not None
            return self._token
        async with self._login_lock:
            if not force and self._token_valid():
                assert self._token is not None
                return self._token
            await self._login()
            assert self._token is not None
            return self._token

    async def _login(self) -> None:
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
                f"login rejected with HTTP {resp.status_code}; check ZAPTEC_USERNAME/ZAPTEC_PASSWORD"
            )
        body = resp.json()
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise ZaptecAuthError("login response contained no access_token")
        expires_in = float(body.get("expires_in") or 3600)
        self._token = token
        self._token_expires_at = self._clock() + expires_in

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
                raise ZaptecRateLimitError("Zaptec API rate limit exceeded", retry_after_seconds=wait)
            if status in _TRANSIENT_STATUSES or (status == 500 and method == "GET" and not _has_code(resp)):
                if attempt < MAX_RETRIES:
                    await self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise ZaptecConnectionError(f"{method} {path}: HTTP {status} after {attempt} retries")
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
                raise ZaptecApiError(f"{method} {path}: HTTP {status}", status=status, body=resp.text[:500])
            if not resp.content:
                return None
            return resp.json()

    async def _backoff(self, attempt: int, retry_after: float | None) -> None:
        delay = _BACKOFF_BASE * (2**attempt) * (1 + random.random() * 0.25)
        if retry_after is not None:
            delay = max(delay, retry_after)
        log.debug("retrying in %.2fs (attempt %d)", delay, attempt + 1)
        await self._sleep(delay)


def _json_or_none(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _has_code(resp: httpx.Response) -> bool:
    body = _json_or_none(resp)
    return isinstance(body, dict) and "Code" in body
```

- [ ] **Step 4: Run tests, ruff, mypy** → pass. (If `random` jitter makes the 429 assertion flaky, it cannot: `max(delay, retry_after)` ≥ 7.)

- [ ] **Step 5: Commit** `git add src/zaptec_mcp_server/zaptec/client.py tests/test_client.py && git commit -m "feat: Zaptec HTTP client with token cache and retry policy"`

---

### Task 5: ZaptecClient — endpoints, pagination, resolution

**Files:**
- Modify: `src/zaptec_mcp_server/zaptec/client.py` (append methods)
- Test: `tests/test_client_endpoints.py`

**Interfaces:**
- Produces on `ZaptecClient`: `list_chargers() -> list[dict]`, `get_charger(id) -> dict`, `get_charger_state(id) -> list[dict]`, `list_installations() -> list[dict]`, `get_installation(id) -> dict`, `get_hierarchy(id) -> dict`, `send_command(charger_id, command_id: int) -> None`, `update_installation(id, body: dict) -> None`, `archived_sessions(*, start: datetime, end: datetime, charger_id: str, max_pages: int = 10) -> list[dict]`, `resolve_charger(charger_id: str | None = None) -> dict`, `resolve_installation(installation_id: str | None = None, *, charger: dict | None = None) -> dict`, `invalidate_lists() -> None`; constants `CMD_PAUSE = 506`, `CMD_RESUME = 507`; `LIST_TTL = 60.0`.

- [ ] **Step 1: Write failing tests**

`tests/test_client_endpoints.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from tests.test_client import CFG, FakeApi, make_client
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
            ("GET", "/api/installation/i1"): [httpx.Response(200, json={"Id": "i1", "Name": "Home"})],
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
```

- [ ] **Step 2: Run** → AttributeError.

- [ ] **Step 3: Append to client.py**

Add near the top constants:

```python
CMD_PAUSE = 506
CMD_RESUME = 507
LIST_TTL = 60.0
```

Add to `__init__`:

```python
        self._chargers_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._installations_cache: tuple[float, list[dict[str, Any]]] | None = None
```

Append methods to `ZaptecClient` (import `datetime`, `timezone` from `datetime`, `field` from `.observations`):

```python
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
        available = {"chargers": [{"id": field(c, "Id"), "name": field(c, "Name")} for c in chargers]}
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


def _data_list(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict):
        data = field(body, "Data") or []
        return [d for d in data if isinstance(d, dict)]
    if isinstance(body, list):
        return [d for d in body if isinstance(d, dict)]
    return []


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run all tests, ruff, mypy** → pass.

- [ ] **Step 5: Commit** `git add -A src tests && git commit -m "feat: client endpoint wrappers, pagination and charger resolution"`

---

### Task 6: Fixtures and formatters for status and installation

**Files:**
- Create: `scripts/sanitize_fixture.py`, `tests/fixtures/chargers.json`, `tests/fixtures/charger_state.json`, `tests/fixtures/installation.json`, `tests/fixtures/hierarchy.json`, `tests/fixtures/sessions_archived.json`, `tests/conftest.py`, `src/zaptec_mcp_server/zaptec/formatters.py`
- Test: `tests/test_formatters.py`

**Interfaces:**
- Produces: `format_status(charger: dict, state: list[dict], installation: dict) -> dict`, `format_installation(installation: dict, hierarchy: dict, chargers: list[dict]) -> dict`, `summarize_mode(state_map: StateMap) -> dict` (`{"code", "name", "hint", "final_stop_active"}`).
- Fixtures loaded by `conftest.py` helper `load_fixture(name) -> Any`.

- [ ] **Step 1: Sanitizer script and fixtures**

`scripts/sanitize_fixture.py`:

```python
"""Sanitize raw Zaptec API responses for use as test fixtures.

Usage: python scripts/sanitize_fixture.py raw.json > tests/fixtures/name.json
Replaces UUIDs (consistently), device ids, names, addresses, coordinates,
signatures and the charger PIN with fake values.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DEVICE_ID = re.compile(r"\b[A-Z]{3}\d{6,}\b")
_STRING_KEYS = {
    "Name": "Garage",
    "SerialNo": "Garage",
    "DeviceName": "Garage",
    "InstallationName": "Example Installation",
    "Address": "Example Street 1",
    "ZipCode": "12345",
    "City": "Exampletown",
    "Pin": "0000",
    "RoutingId": "routing-redacted",
    "SD": "signature-redacted",
    "ContactEmail": "owner@example.com",
    "Email": "owner@example.com",
    "FullName": "Example Owner",
    "TokenName": None,
}
_NUMERIC_KEYS = {"Latitude": 0.0, "Longitude": 0.0}


class Sanitizer:
    def __init__(self) -> None:
        self.uuids: dict[str, str] = {}

    def fake_uuid(self, real: str) -> str:
        if real not in self.uuids:
            n = len(self.uuids) + 1
            self.uuids[real] = f"{n:08d}-0000-4000-8000-{n:012d}"
        return self.uuids[real]

    def text(self, value: str) -> str:
        value = _UUID.sub(lambda m: self.fake_uuid(m.group(0)), value)
        value = _DEVICE_ID.sub("ZPR000001", value)
        if value.startswith("OCMF|"):
            try:
                head, body, *rest = value.split("|")
                data = json.loads(body)
                data["GS"] = "ZPR000001"
                value = "|".join([head, json.dumps(data, separators=(",", ":"))] + ['{"SA":"redacted"}'] if rest else [head, json.dumps(data)])
            except (ValueError, KeyError):
                pass
        return value

    def walk(self, node: Any, key: str | None = None) -> Any:
        if isinstance(node, dict):
            return {k: self.walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [self.walk(v, key) for v in node]
        if key is not None:
            lookup = key[:1].upper() + key[1:]
            if lookup in _STRING_KEYS and isinstance(node, str):
                return _STRING_KEYS[lookup]
            if lookup in _NUMERIC_KEYS and isinstance(node, (int, float)):
                return _NUMERIC_KEYS[lookup]
        if isinstance(node, str):
            return self.text(node)
        return node


def main() -> None:
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(Sanitizer().walk(raw), indent=1))


if __name__ == "__main__":
    main()
```

Run it against the raw captures in the scratchpad (`raw_chargers.json`, `state_raw.json`, `raw_installation.json`, `raw_hierarchy.json`, `raw_archived.json`) writing `tests/fixtures/{chargers,charger_state,installation,hierarchy,sessions_archived}.json`, then `grep -c "<serial-prefix>\|<owner-name>\|<street>\|<town>\|<charger-id-prefix>\|<installation-id-prefix>" tests/fixtures/*.json` must print 0 for every file. Note: the `InstallationName` of the charger list must map to the same fake as the installation `Name` — set `"InstallationName": "Example Installation"` and, in `tests/fixtures/installation.json`, verify `Name` became `Garage` via `_STRING_KEYS["Name"]`; override by hand to `"Example Installation"` so status/installation fixtures agree.

`tests/conftest.py`:

```python
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def chargers() -> list[dict[str, Any]]:
    return list(load_fixture("chargers")["Data"])


@pytest.fixture
def charger(chargers: list[dict[str, Any]]) -> dict[str, Any]:
    return chargers[0]


@pytest.fixture
def charger_state() -> list[dict[str, Any]]:
    return list(load_fixture("charger_state"))


@pytest.fixture
def installation() -> dict[str, Any]:
    return dict(load_fixture("installation"))


@pytest.fixture
def hierarchy() -> dict[str, Any]:
    return dict(load_fixture("hierarchy"))


@pytest.fixture
def sessions_archived() -> list[dict[str, Any]]:
    return list(load_fixture("sessions_archived")["sessions"])
```

- [ ] **Step 2: Write failing tests**

`tests/test_formatters.py` (status/installation part):

```python
from __future__ import annotations

from typing import Any

from zaptec_mcp_server.zaptec.formatters import format_installation, format_status


def test_format_status_shape(charger: dict[str, Any], charger_state: list[dict[str, Any]], installation: dict[str, Any]) -> None:
    out = format_status(charger, charger_state, installation)
    assert out["charger"]["name"] == "Garage"
    assert out["charger"]["id"] == charger["Id"]
    assert out["charger"]["model"] == "Zaptec Go 2"
    assert out["charger"]["firmware"] == "3.1.0.8"
    assert out["charger"]["online"] is True
    assert out["operating_mode"] == {
        "code": 3,
        "name": "connected_charging",
        "hint": "charging",
    }
    ch = out["charging"]
    assert ch["power_kw"] == 0.017
    assert ch["session_energy_kwh"] == 11.284
    assert ch["charge_current_set_a"] == 19.992
    assert ch["active_phases"] == ["L3"]
    assert ch["final_stop_active"] is False
    assert ch["current_a"] == {"l1": 0.477, "l2": 0.485, "l3": 0.483}
    assert ch["voltage_v"]["l1"] == 239.881
    assert ch["cable_rating_a"] == 20
    assert ch["charger_max_current_a"] == 32.0
    assert ch["charger_min_current_a"] == 6.0
    inst = out["installation"]
    assert inst["name"] == "Example Installation"
    assert inst["max_current_a"] == 32.0
    assert inst["available_current_a"] is None
    assert inst["available_current_mode"] == "manual"
    diag = out["diagnostics"]
    assert diag["temperature_internal_c"] == 41.457
    assert diag["signal_strength_dbm"] == -74.0
    assert diag["communication_mode"] == "Wifi"
    assert out["authorization_required"] is False
    assert out["observed_at"].startswith("2026-09-22T14:30:18")


def test_format_status_handles_sparse_state() -> None:
    out = format_status({"Id": "x", "Name": "n", "DeviceType": 1, "IsOnline": False}, [], {})
    assert out["operating_mode"]["code"] is None
    assert out["operating_mode"]["name"] == "unknown"
    assert out["charging"]["power_kw"] is None
    assert out["charger"]["model"] == "Zaptec Pro"
    assert out["charger"]["online"] is False


def test_format_installation(installation: dict[str, Any], hierarchy: dict[str, Any], chargers: list[dict[str, Any]]) -> None:
    out = format_installation(installation, hierarchy, chargers)
    assert out["id"] == installation["Id"]
    assert out["name"] == "Example Installation"
    assert out["address"] == {"street": "Example Street 1", "zip_code": "12345", "city": "Exampletown"}
    assert out["timezone"] == "Europe/Berlin"
    assert out["max_current_a"] == 32.0
    assert out["available_current_a"] is None
    assert out["available_current_mode"] == "manual"
    assert out["network_type"] == "TN_3_phase"
    assert out["use_load_balancing"] is True
    assert out["authentication_required"] is False
    assert "PowerManagement_Apm_SurplusMode" in out["features_available"]
    assert out["features_enabled"] == []
    assert out["circuits"][0]["name"] == "Charge circuit"
    assert out["circuits"][0]["max_current_a"] == 32.0
    c = out["circuits"][0]["chargers"][0]
    assert c["name"] == "Garage"
    assert c["online"] is True
    assert c["operating_mode"] == "connected_charging"
    assert c["model"] == "Zaptec Go"
```

- [ ] **Step 3: Run** → ImportError.

- [ ] **Step 4: Implement formatters (status + installation)**

`src/zaptec_mcp_server/zaptec/formatters.py`:

```python
"""Pure formatters: raw API dicts -> tool payloads. No I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .observations import (
    AVAILABLE_CURRENT_MODES,
    DEVICE_TYPES,
    MODE_HINTS,
    NETWORK_TYPES,
    OPERATING_MODES,
    Obs,
    StateMap,
    decode_features,
    decode_phases,
    field,
    parse_api_datetime,
    parse_ocmf,
)


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def summarize_mode(sm: StateMap, fallback_code: int | None = None) -> dict[str, Any]:
    code = sm.get_int(Obs.OPERATION_MODE)
    if code is None:
        code = fallback_code
    name = OPERATING_MODES.get(code, "unknown") if code is not None else "unknown"
    hint = MODE_HINTS.get(code, MODE_HINTS[0]) if code is not None else MODE_HINTS[0]
    return {"code": code, "name": name, "hint": hint}


def _model_name(charger: dict[str, Any], ocmf: dict[str, Any]) -> str:
    product = ocmf.get("GI")
    if isinstance(product, str) and product:
        return product
    return DEVICE_TYPES.get(_int_or_none(field(charger, "DeviceType")) or 0, "Unknown")


def format_status(
    charger: dict[str, Any], state: list[dict[str, Any]], installation: dict[str, Any]
) -> dict[str, Any]:
    sm = StateMap(state)
    ocmf = parse_ocmf(sm.get(Obs.SIGNED_METER_VALUE))
    mode = summarize_mode(sm, _int_or_none(field(charger, "OperatingMode")))
    power_w = sm.get_float(Obs.TOTAL_CHARGE_POWER)
    return {
        "charger": {
            "id": field(charger, "Id"),
            "name": field(charger, "Name"),
            "device_id": field(charger, "DeviceId"),
            "model": _model_name(charger, ocmf),
            "firmware": ocmf.get("GV"),
            "online": bool(field(charger, "IsOnline", False)),
            "active": bool(field(charger, "Active", False)),
        },
        "operating_mode": mode,
        "charging": {
            "power_kw": _r(None if power_w is None else power_w / 1000.0),
            "session_energy_kwh": _r(sm.get_float(Obs.SESSION_ENERGY)),
            "charge_current_set_a": _r(sm.get_float(Obs.CHARGE_CURRENT_SET)),
            "active_phases": decode_phases(sm.get_int(Obs.ACTIVE_PHASES)),
            "final_stop_active": sm.get_bool(Obs.FINAL_STOP_ACTIVE),
            "current_a": {
                "l1": _r(sm.get_float(Obs.CURRENT_L1)),
                "l2": _r(sm.get_float(Obs.CURRENT_L2)),
                "l3": _r(sm.get_float(Obs.CURRENT_L3)),
            },
            "voltage_v": {
                "l1": _r(sm.get_float(Obs.VOLTAGE_L1)),
                "l2": _r(sm.get_float(Obs.VOLTAGE_L2)),
                "l3": _r(sm.get_float(Obs.VOLTAGE_L3)),
            },
            "cable_rating_a": sm.get_int(Obs.CABLE_TYPE),
            "charger_max_current_a": sm.get_float(Obs.CHARGER_MAX_CURRENT),
            "charger_min_current_a": sm.get_float(Obs.CHARGER_MIN_CURRENT),
        },
        "installation": {
            "id": field(installation, "Id"),
            "name": field(installation, "Name") or field(charger, "InstallationName"),
            "available_current_a": field(installation, "AvailableCurrent"),
            "max_current_a": field(installation, "MaxCurrent"),
            "available_current_mode": AVAILABLE_CURRENT_MODES.get(
                _int_or_none(field(installation, "AvailableCurrentMode")) or 0, "manual"
            ),
        },
        "diagnostics": {
            "temperature_internal_c": _r(sm.get_float(Obs.TEMPERATURE_INTERNAL)),
            "humidity_pct": _r(sm.get_float(Obs.HUMIDITY)),
            "signal_strength_dbm": sm.get_float(Obs.SIGNAL_STRENGTH),
            "communication_mode": sm.get(Obs.COMMUNICATION_MODE),
            "warnings": sm.get(Obs.WARNINGS),
        },
        "authorization_required": bool(field(charger, "IsAuthorizationRequired", False)),
        "observed_at": sm.newest_timestamp(),
    }


def _charger_summary(charger: dict[str, Any]) -> dict[str, Any]:
    mode = _int_or_none(field(charger, "OperatingMode"))
    return {
        "id": field(charger, "Id"),
        "name": field(charger, "Name"),
        "device_id": field(charger, "DeviceId"),
        "model": DEVICE_TYPES.get(_int_or_none(field(charger, "DeviceType")) or 0, "Unknown"),
        "online": field(charger, "IsOnline"),
        "operating_mode": OPERATING_MODES.get(mode, "unknown") if mode is not None else "unknown",
    }


def format_installation(
    installation: dict[str, Any], hierarchy: dict[str, Any], chargers: list[dict[str, Any]]
) -> dict[str, Any]:
    by_id = {field(c, "Id"): c for c in chargers}
    circuits = []
    for circuit in field(hierarchy, "Circuits") or []:
        members = []
        for entry in field(circuit, "Chargers") or []:
            full = by_id.get(field(entry, "Id"), entry)
            members.append(_charger_summary(full))
        circuits.append(
            {
                "id": field(circuit, "Id"),
                "name": field(circuit, "Name"),
                "max_current_a": field(circuit, "MaxCurrent"),
                "active": field(circuit, "Active"),
                "chargers": members,
            }
        )
    return {
        "id": field(installation, "Id"),
        "name": field(installation, "Name"),
        "address": {
            "street": field(installation, "Address"),
            "zip_code": field(installation, "ZipCode"),
            "city": field(installation, "City"),
        },
        "timezone": field(installation, "TimeZoneIanaName"),
        "max_current_a": field(installation, "MaxCurrent"),
        "available_current_a": field(installation, "AvailableCurrent"),
        "available_current_phases_a": {
            "l1": field(installation, "AvailableCurrentPhase1"),
            "l2": field(installation, "AvailableCurrentPhase2"),
            "l3": field(installation, "AvailableCurrentPhase3"),
        },
        "available_current_mode": AVAILABLE_CURRENT_MODES.get(
            _int_or_none(field(installation, "AvailableCurrentMode")) or 0, "manual"
        ),
        "network_type": NETWORK_TYPES.get(_int_or_none(field(installation, "NetworkType")) or 0, "unknown"),
        "use_load_balancing": field(installation, "UseLoadBalancing"),
        "authentication_required": bool(field(installation, "IsRequiredAuthentication", False)),
        "features_available": decode_features(_int_or_none(field(installation, "AvailableFeatures"))),
        "features_enabled": decode_features(_int_or_none(field(installation, "EnabledFeatures"))),
        "circuits": circuits,
    }
```

(`datetime`/`ZoneInfo` imports are used by Task 7; keep them and let ruff complain until then, or add them in Task 7 — add them in Task 7.)

- [ ] **Step 5: Run tests, ruff, mypy** → pass.

- [ ] **Step 6: Commit** `git add scripts tests/fixtures tests/conftest.py tests/test_formatters.py src && git commit -m "feat: status and installation formatters with sanitized fixtures"`

---

### Task 7: History formatter with optional cost

**Files:**
- Modify: `src/zaptec_mcp_server/zaptec/formatters.py`
- Test: `tests/test_formatters.py` (append)

**Interfaces:**
- Produces: `format_history(sessions: list[dict], *, tz: ZoneInfo, time_range: str, start: datetime, end: datetime, price_per_kwh: float | None, currency: str, max_sessions: int = 500) -> dict`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_formatters.py`)

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from zaptec_mcp_server.zaptec.formatters import format_history

TZ = ZoneInfo("Europe/Berlin")


def _range() -> tuple[datetime, datetime]:
    return datetime(2026, 9, 1, tzinfo=TZ), datetime(2026, 9, 22, 16, 0, tzinfo=TZ)


def test_format_history_without_price(sessions_archived: list[dict[str, Any]]) -> None:
    start, end = _range()
    out = format_history(
        sessions_archived, tz=TZ, time_range="month", start=start, end=end, price_per_kwh=None, currency="EUR"
    )
    assert out["time_range"] == "month"
    assert out["start"] == "2026-09-01T00:00:00+02:00"
    assert out["timezone"] == "Europe/Berlin"
    s = out["summary"]
    assert s["session_count"] == 3
    assert s["energy_kwh"] == 27.575
    assert s["duration_hours"] == 6.754
    assert "cost" not in s
    first = out["sessions"][0]
    assert first["start"] == "2026-09-20T13:11:06+02:00"
    assert first["end"] == "2026-09-20T14:06:24+02:00"
    assert first["duration_minutes"] == 55
    assert first["energy_kwh"] == 9.205
    assert first["charger_name"] == "Garage"
    assert first["stopped_by_rfid"] is False
    assert first["offline"] is False
    assert first["aborted"] is False
    assert "cost" not in first
    assert out["truncated"] is False


def test_format_history_with_price_and_truncation(sessions_archived: list[dict[str, Any]]) -> None:
    start, end = _range()
    out = format_history(
        sessions_archived, tz=TZ, time_range="month", start=start, end=end, price_per_kwh=0.30, currency="EUR", max_sessions=2
    )
    assert out["summary"]["cost"] == 8.27
    assert out["summary"]["price_per_kwh"] == 0.30
    assert out["summary"]["currency"] == "EUR"
    assert out["sessions"][0]["cost"] == 2.76
    assert len(out["sessions"]) == 2
    assert out["truncated"] is True
    assert out["summary"]["session_count"] == 3  # summary covers all sessions


def test_format_history_skips_voided_and_sorts() -> None:
    sessions = [
        {"id": "b", "startDateTime": "2026-09-05T10:00:00Z", "endDateTime": "2026-09-05T11:00:00Z", "energy": 2.0},
        {"id": "a", "startDateTime": "2026-09-04T10:00:00Z", "endDateTime": "2026-09-04T10:30:00Z", "energy": 1.0},
        {"id": "v", "startDateTime": "2026-09-06T10:00:00Z", "endDateTime": "2026-09-06T11:00:00Z", "energy": 9.0, "voided": True},
    ]
    start, end = _range()
    out = format_history(sessions, tz=TZ, time_range="custom", start=start, end=end, price_per_kwh=None, currency="EUR")
    assert [s["id"] for s in out["sessions"]] == ["a", "b"]
    assert out["summary"]["energy_kwh"] == 3.0
    assert out["summary"]["duration_hours"] == 1.5
```

- [ ] **Step 2: Run** → ImportError for `format_history`.

- [ ] **Step 3: Implement** (append to formatters.py; add `from datetime import datetime` and `from zoneinfo import ZoneInfo` imports)

```python
def _session_row(s: dict[str, Any], tz: ZoneInfo, price: float | None) -> dict[str, Any] | None:
    start = parse_api_datetime(field(s, "StartDateTime"))
    end = parse_api_datetime(field(s, "EndDateTime"))
    if start is None:
        return None
    energy = float(field(s, "Energy") or 0.0)
    duration_min = None if end is None else round((end - start).total_seconds() / 60)
    row: dict[str, Any] = {
        "id": field(s, "Id"),
        "start": start.astimezone(tz).isoformat(timespec="seconds"),
        "end": None if end is None else end.astimezone(tz).isoformat(timespec="seconds"),
        "duration_minutes": duration_min,
        "energy_kwh": round(energy, 3),
        "charger_name": field(s, "DeviceName"),
        "stopped_by_rfid": bool(field(s, "StoppedByRfid", False)),
        "offline": bool(field(s, "Offline", False)),
        "aborted": bool(field(s, "Aborted", False)),
    }
    if price is not None:
        row["cost"] = round(energy * price, 2)
    return row


def format_history(
    sessions: list[dict[str, Any]],
    *,
    tz: ZoneInfo,
    time_range: str,
    start: datetime,
    end: datetime,
    price_per_kwh: float | None,
    currency: str,
    max_sessions: int = 500,
) -> dict[str, Any]:
    rows = [
        r
        for s in sessions
        if not field(s, "Voided", False)
        for r in [_session_row(s, tz, price_per_kwh)]
        if r is not None
    ]
    rows.sort(key=lambda r: r["start"])
    energy = sum(r["energy_kwh"] for r in rows)
    minutes = sum(r["duration_minutes"] or 0 for r in rows)
    summary: dict[str, Any] = {
        "session_count": len(rows),
        "energy_kwh": round(energy, 3),
        "duration_hours": round(minutes / 60.0, 3),
    }
    if price_per_kwh is not None:
        summary["cost"] = round(energy * price_per_kwh, 2)
        summary["price_per_kwh"] = price_per_kwh
        summary["currency"] = currency
    return {
        "time_range": time_range,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "timezone": str(tz.key),
        "summary": summary,
        "sessions": rows[:max_sessions],
        "truncated": len(rows) > max_sessions,
    }
```

Check the fixture-derived expectations: durations 55 + 238 + 112 min = 405 min = 6.75 h → the test expects `6.754`; compute from the fixture exactly (session 1: 11:11:06.77→12:06:24.49 = 55.3 min → round 55; session 2: 06:23:04→10:20:49 = 237.75 → 238; session 3: 10:48:43→12:40:56 = 112.2 → 112; total 405 min = 6.75 h). Adjust the test expectation to the computed value `6.75` and the summary `duration_hours` to what the code yields; the truth is the code path above, the numbers in the test must match it (fix the test, not the rounding).

- [ ] **Step 4: Run tests, ruff, mypy** → pass.

- [ ] **Step 5: Commit** `git commit -am "feat: charge history formatter with optional cost" `

---

### Task 8: ZaptecTools — read tools with caching

**Files:**
- Create: `src/zaptec_mcp_server/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `ZaptecClient` (Tasks 4–5), formatters (6–7), `CacheManager`, `ServerConfig`, `resolve_range`.
- Produces: `ZaptecTools(client, cache, cfg, *, clock=time.monotonic, now=lambda: datetime.now(timezone.utc))` with `await get_status(charger_id=None)`, `await get_installation(installation_id=None)`, `await get_charge_history(charger_id=None, time_range="month", start_date=None, end_date=None)`; constants `TTL_STATUS = 15.0`, `TTL_INSTALLATION = 300.0`, `TTL_HISTORY = 300.0`.

- [ ] **Step 1: Write failing tests**

`tests/test_server.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from tests.conftest import load_fixture
from tests.test_client import FakeApi
from zaptec_mcp_server.cache.manager import CacheManager
from zaptec_mcp_server.config import ServerConfig
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.zaptec.client import ZaptecClient

NOW = datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)


def build(api: FakeApi, env: dict[str, str] | None = None, clock: list[float] | None = None) -> ZaptecTools:
    cfg = ServerConfig.from_env({"ZAPTEC_USERNAME": "u@example.com", "ZAPTEC_PASSWORD": "pw123456", **(env or {})})
    tick = clock or [1000.0]

    async def no_sleep(_: float) -> None:
        pass

    client = ZaptecClient(cfg, transport=api.transport(), sleep=no_sleep, clock=lambda: tick[0])
    return ZaptecTools(client=client, cache=CacheManager(), cfg=cfg, clock=lambda: tick[0], now=lambda: NOW)


def fixture_api(state: list[dict[str, Any]] | None = None, extra: dict[tuple[str, str], list[httpx.Response]] | None = None) -> FakeApi:
    chargers = load_fixture("chargers")
    cid = chargers["Data"][0]["Id"]
    iid = chargers["Data"][0]["InstallationId"]
    script: dict[tuple[str, str], list[httpx.Response]] = {
        ("GET", "/api/chargers"): [httpx.Response(200, json=chargers)],
        ("GET", f"/api/chargers/{cid}/state"): [httpx.Response(200, json=state if state is not None else load_fixture("charger_state"))],
        ("GET", f"/api/installation/{iid}"): [httpx.Response(200, json=load_fixture("installation"))],
        ("GET", f"/api/installation/{iid}/hierarchy"): [httpx.Response(200, json=load_fixture("hierarchy"))],
        ("GET", "/api/sessions/archived"): [httpx.Response(200, json=load_fixture("sessions_archived"))],
    }
    script.update(extra or {})
    return FakeApi(script)


async def test_get_status_and_cache() -> None:
    api = fixture_api()
    tools = build(api)
    out = await tools.get_status()
    assert out["operating_mode"]["name"] == "connected_charging"
    await tools.get_status()
    assert len([c for c in api.calls if c.url.path.endswith("/state")]) == 1


async def test_get_installation() -> None:
    tools = build(fixture_api())
    out = await tools.get_installation()
    assert out["timezone"] == "Europe/Berlin"
    assert out["circuits"][0]["chargers"][0]["name"] == "Garage"


async def test_get_charge_history_uses_installation_timezone_and_price() -> None:
    api = fixture_api()
    tools = build(api, {"ZAPTEC_PRICE_PER_KWH": "0.30"})
    out = await tools.get_charge_history(time_range="month")
    assert out["timezone"] == "Europe/Berlin"
    assert out["start"] == "2026-09-01T00:00:00+02:00"
    assert out["summary"]["cost"] == 8.27
    call = [c for c in api.calls if c.url.path == "/api/sessions/archived"][0]
    assert call.url.params["From"] == "2026-08-31T22:00:00Z"


async def test_get_charge_history_custom_requires_dates() -> None:
    tools = build(fixture_api())
    with pytest.raises(ValueError):
        await tools.get_charge_history(time_range="custom")
    out = await tools.get_charge_history(time_range="custom", start_date="2026-09-01", end_date="2026-09-21")
    assert out["end"] == "2026-09-22T00:00:00+02:00"
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement**

`src/zaptec_mcp_server/server.py`:

```python
"""Tool implementations: caching, guards and orchestration over ZaptecClient."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

from .cache.manager import CacheManager
from .config import ServerConfig
from .zaptec.client import ZaptecClient
from .zaptec.formatters import format_history, format_installation, format_status
from .zaptec.observations import field
from .zaptec.timeranges import resolve_range

log = logging.getLogger(__name__)

TTL_STATUS = 15.0
TTL_INSTALLATION = 300.0
TTL_HISTORY = 300.0


def _tz_of(installation: dict[str, Any]) -> ZoneInfo:
    name = field(installation, "TimeZoneIanaName")
    if isinstance(name, str) and name:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - unknown zone name from API
            log.warning("unknown timezone %r, falling back to UTC", name)
    return ZoneInfo("UTC")


def _parse_date(s: str | None) -> date | None:
    return None if s is None else date.fromisoformat(s)


class ZaptecTools:
    def __init__(
        self,
        *,
        client: ZaptecClient,
        cache: CacheManager,
        cfg: ServerConfig,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._client = client
        self._cache = cache
        self._cfg = cfg
        self._clock = clock
        self._now = now
        self._last_current_update: float | None = None

    # -- read tools -----------------------------------------------------------

    async def get_status(self, *, charger_id: str | None = None) -> dict[str, Any]:
        async def loader() -> dict[str, Any]:
            charger = await self._client.resolve_charger(charger_id)
            state = await self._client.get_charger_state(field(charger, "Id"))
            installation = await self._client.resolve_installation(charger=charger)
            return format_status(charger, state, installation)

        return cast(
            dict[str, Any],
            await self._cache.get_or_load("status", {"charger_id": charger_id}, ttl=TTL_STATUS, loader=loader),
        )

    async def get_installation(self, *, installation_id: str | None = None) -> dict[str, Any]:
        async def loader() -> dict[str, Any]:
            installation = await self._client.resolve_installation(installation_id)
            iid = field(installation, "Id")
            hierarchy = await self._client.get_hierarchy(iid)
            chargers = await self._client.list_chargers()
            return format_installation(installation, hierarchy, chargers)

        return cast(
            dict[str, Any],
            await self._cache.get_or_load(
                "installation", {"installation_id": installation_id}, ttl=TTL_INSTALLATION, loader=loader
            ),
        )

    async def get_charge_history(
        self,
        *,
        charger_id: str | None = None,
        time_range: str = "month",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        async def loader() -> dict[str, Any]:
            charger = await self._client.resolve_charger(charger_id)
            installation = await self._client.resolve_installation(charger=charger)
            tz = _tz_of(installation)
            start, end = resolve_range(
                time_range,
                now=self._now(),
                tz=tz,
                start_date=_parse_date(start_date),
                end_date=_parse_date(end_date),
            )
            sessions = await self._client.archived_sessions(
                start=start, end=end, charger_id=field(charger, "Id")
            )
            return format_history(
                sessions,
                tz=tz,
                time_range=time_range,
                start=start,
                end=end,
                price_per_kwh=self._cfg.price_per_kwh,
                currency=self._cfg.currency,
            )

        args = {
            "charger_id": charger_id,
            "time_range": time_range,
            "start_date": start_date,
            "end_date": end_date,
        }
        return cast(dict[str, Any], await self._cache.get_or_load("history", args, ttl=TTL_HISTORY, loader=loader))
```

- [ ] **Step 4: Run tests, ruff, mypy** → pass.

- [ ] **Step 5: Commit** `git add src/zaptec_mcp_server/server.py tests/test_server.py && git commit -m "feat: read tools with per-tool caching"`

---

### Task 9: Control tools — pause, resume, available current with guards

**Files:**
- Modify: `src/zaptec_mcp_server/server.py`
- Test: `tests/test_server_control.py`

**Interfaces:**
- Produces on `ZaptecTools`: `await pause_charging(charger_id=None) -> dict`, `await resume_charging(charger_id=None) -> dict`, `await set_available_current(amps: float | None, installation_id=None, force=False) -> dict`.
- Result shapes: `{"ok": True, "command": "pause"|"resume", "charger": {"id","name"}, "previous_state": {"code","name","hint"}, "note": str}` and `{"ok": True, "installation": {"id","name"}, "previous_available_current_a", "requested_available_current_a", "new_available_current_a", "max_current_a", "note"}`.

- [ ] **Step 1: Write failing tests**

`tests/test_server_control.py`:

```python
from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.conftest import load_fixture
from tests.test_server import build, fixture_api
from zaptec_mcp_server.utils.errors import ZaptecCommandRejectedError, ZaptecGuardError


def state_with(mode: int, final_stop: int = 0) -> list[dict[str, Any]]:
    base = [s for s in load_fixture("charger_state") if s["StateId"] not in (710, 718)]
    base.append({"StateId": 710, "ValueAsString": str(mode), "Timestamp": "2026-09-22T14:40:00"})
    base.append({"StateId": 718, "ValueAsString": str(final_stop), "Timestamp": "2026-09-22T14:40:00"})
    return base


def cid() -> str:
    return str(load_fixture("chargers")["Data"][0]["Id"])


def iid() -> str:
    return str(load_fixture("chargers")["Data"][0]["InstallationId"])


async def test_pause_when_charging() -> None:
    api = fixture_api(state_with(3), {("POST", f"/api/chargers/{cid()}/sendCommand/506"): [httpx.Response(200)]})
    tools = build(api)
    await tools.get_status()  # warm cache; pause must invalidate it
    out = await tools.pause_charging()
    assert out["ok"] is True and out["command"] == "pause"
    assert out["previous_state"]["name"] == "connected_charging"
    assert any(c.url.path.endswith("/sendCommand/506") for c in api.calls)
    await tools.get_status()
    assert len([c for c in api.calls if c.url.path.endswith("/state")]) == 3  # status, pause check, status again


async def test_pause_rejected_when_not_charging() -> None:
    tools = build(fixture_api(state_with(5, 1)))
    with pytest.raises(ZaptecGuardError) as info:
        await tools.pause_charging()
    assert info.value.payload["operating_mode"]["name"] == "connected_finished"
    assert "already paused" in str(info.value)


async def test_resume_when_paused() -> None:
    api = fixture_api(state_with(5, 1), {("POST", f"/api/chargers/{cid()}/sendCommand/507"): [httpx.Response(200)]})
    out = await build(api).resume_charging()
    assert out["command"] == "resume"


@pytest.mark.parametrize(
    ("mode", "final_stop", "phrase"),
    [(3, 0, "already charging"), (1, 0, "no vehicle"), (2, 0, "waiting"), (5, 0, "vehicle")],
)
async def test_resume_guard_messages(mode: int, final_stop: int, phrase: str) -> None:
    tools = build(fixture_api(state_with(mode, final_stop)))
    with pytest.raises(ZaptecGuardError) as info:
        await tools.resume_charging()
    assert phrase in str(info.value)


async def test_cloud_rejection_propagates() -> None:
    api = fixture_api(
        state_with(5, 1),
        {("POST", f"/api/chargers/{cid()}/sendCommand/507"): [httpx.Response(500, json={"Code": 528, "Details": "nope"})]},
    )
    with pytest.raises(ZaptecCommandRejectedError):
        await build(api).resume_charging()


def _updated_installation(amps: float | None) -> dict[str, Any]:
    inst = dict(load_fixture("installation"))
    inst["AvailableCurrent"] = amps
    return inst


async def test_set_available_current_happy_path_and_guard() -> None:
    clock = [1000.0]
    api = fixture_api(
        None,
        {
            ("POST", f"/api/installation/{iid()}/update"): [httpx.Response(200)],
            ("GET", f"/api/installation/{iid()}"): [
                httpx.Response(200, json=load_fixture("installation")),
                httpx.Response(200, json=_updated_installation(10.0)),
            ],
        },
    )
    tools = build(api, clock=clock)
    out = await tools.set_available_current(10)
    assert out["ok"] is True
    assert out["previous_available_current_a"] is None
    assert out["new_available_current_a"] == 10.0
    assert out["max_current_a"] == 32.0
    post = [c for c in api.calls if c.method == "POST" and c.url.path.endswith("/update")][0]
    assert post.content == b'{"availableCurrent": 10.0}'
    clock[0] += 100
    with pytest.raises(ZaptecGuardError) as info:
        await tools.set_available_current(12)
    assert info.value.payload["seconds_until_allowed"] == 800
    clock[0] += 900
    await tools.set_available_current(12)


async def test_set_available_current_force_and_reset() -> None:
    clock = [1000.0]
    api = fixture_api(None, {("POST", f"/api/installation/{iid()}/update"): [httpx.Response(200)]})
    tools = build(api, clock=clock)
    await tools.set_available_current(16)
    await tools.set_available_current(None, force=True)
    posts = [c for c in api.calls if c.method == "POST" and c.url.path.endswith("/update")]
    assert posts[1].content == b'{"availableCurrent": null}'


async def test_set_available_current_validation() -> None:
    tools = build(fixture_api())
    with pytest.raises(ZaptecGuardError):
        await tools.set_available_current(40)
    with pytest.raises(ZaptecGuardError):
        await tools.set_available_current(-1)


async def test_guard_disabled_by_config() -> None:
    api = fixture_api(None, {("POST", f"/api/installation/{iid()}/update"): [httpx.Response(200)]})
    tools = build(api, {"ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL": "0"})
    await tools.set_available_current(8)
    await tools.set_available_current(9)
```

- [ ] **Step 2: Run** → AttributeError.

- [ ] **Step 3: Implement** (append to `ZaptecTools`; add imports `from .utils.errors import ZaptecGuardError`, `from .zaptec.client import CMD_PAUSE, CMD_RESUME`, `from .zaptec.formatters import summarize_mode`, `from .zaptec.observations import Obs, StateMap`)

```python
    # -- control tools --------------------------------------------------------

    async def _fresh_mode(self, charger_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        charger = await self._client.resolve_charger(charger_id)
        state = await self._client.get_charger_state(field(charger, "Id"))
        sm = StateMap(state)
        mode = summarize_mode(sm, None)
        mode["final_stop_active"] = sm.get_bool(Obs.FINAL_STOP_ACTIVE)
        return charger, mode

    async def pause_charging(self, *, charger_id: str | None = None) -> dict[str, Any]:
        charger, mode = await self._fresh_mode(charger_id)
        code = mode["code"]
        if code != 3:
            if code == 5 and mode["final_stop_active"]:
                reason = "charging is already paused"
            elif code == 5:
                reason = "the vehicle is connected but not charging (finished or stopped by the vehicle)"
            elif code == 1:
                reason = "no vehicle is connected"
            elif code == 2:
                reason = "the charger is waiting for authorization or for the vehicle to request power"
            else:
                reason = "the charger state is unknown"
            raise ZaptecGuardError(
                f"cannot pause: {reason}", {"operating_mode": mode, "charger_id": field(charger, "Id")}
            )
        await self._client.send_command(field(charger, "Id"), CMD_PAUSE)
        self._cache.invalidate("status")
        return {
            "ok": True,
            "command": "pause",
            "charger": {"id": field(charger, "Id"), "name": field(charger, "Name")},
            "previous_state": mode,
            "note": "Pause requested. The charger reports mode connected_finished with final_stop_active=true within a few seconds.",
        }

    async def resume_charging(self, *, charger_id: str | None = None) -> dict[str, Any]:
        charger, mode = await self._fresh_mode(charger_id)
        code = mode["code"]
        if not (code == 5 and mode["final_stop_active"]):
            if code == 3:
                reason = "the charger is already charging"
            elif code == 1:
                reason = "no vehicle is connected"
            elif code == 2:
                reason = "the charger is waiting for authorization or for the vehicle; resume only works for a paused session"
            elif code == 5:
                reason = "the session is not paused by the charger; the vehicle stopped charging itself (full battery, schedule or app)"
            else:
                reason = "the charger state is unknown"
            raise ZaptecGuardError(
                f"cannot resume: {reason}", {"operating_mode": mode, "charger_id": field(charger, "Id")}
            )
        await self._client.send_command(field(charger, "Id"), CMD_RESUME)
        self._cache.invalidate("status")
        return {
            "ok": True,
            "command": "resume",
            "charger": {"id": field(charger, "Id"), "name": field(charger, "Name")},
            "previous_state": mode,
            "note": "Resume requested. Charging restarts within a few seconds if the vehicle accepts power.",
        }

    async def set_available_current(
        self,
        amps: float | None,
        *,
        installation_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        installation = await self._client.resolve_installation(installation_id)
        iid = field(installation, "Id")
        max_current = field(installation, "MaxCurrent")
        previous = field(installation, "AvailableCurrent")
        if amps is not None:
            amps = float(amps)
            if amps < 0:
                raise ZaptecGuardError("amps must be >= 0", {"max_current_a": max_current})
            if isinstance(max_current, (int, float)) and amps > float(max_current):
                raise ZaptecGuardError(
                    f"amps {amps} exceeds the installation maximum of {max_current} A",
                    {"max_current_a": max_current},
                )
        interval = self._cfg.min_current_update_interval
        if interval > 0 and not force and self._last_current_update is not None:
            elapsed = self._clock() - self._last_current_update
            if elapsed < interval:
                wait = round(interval - elapsed)
                raise ZaptecGuardError(
                    f"available current was changed {round(elapsed)} s ago; Zaptec recommends at most one change "
                    f"every {round(interval)} s. Wait {wait} s or pass force=true.",
                    {"seconds_until_allowed": wait, "min_interval_seconds": interval},
                )
        await self._client.update_installation(iid, {"availableCurrent": amps})
        self._last_current_update = self._clock()
        self._cache.invalidate("status")
        self._cache.invalidate("installation")
        self._client.invalidate_lists()
        refreshed = await self._client.get_installation(iid)
        return {
            "ok": True,
            "installation": {"id": iid, "name": field(installation, "Name")},
            "previous_available_current_a": previous,
            "requested_available_current_a": amps,
            "new_available_current_a": field(refreshed, "AvailableCurrent"),
            "max_current_a": max_current,
            "note": (
                "Vehicles adapt within about 5 seconds. null means the installation reverted to its maximum. "
                "Avoid changing this more than once every 15 minutes."
            ),
        }
```

Note for the tests: `FakeApi` returns the last scripted response repeatedly once the queue has one element, so the two-element list for `GET /api/installation/{id}` yields the original first, then the updated one forever.

- [ ] **Step 4: Run all tests, ruff, mypy** → pass.

- [ ] **Step 5: Commit** `git add -A src tests && git commit -m "feat: pause, resume and available-current tools with guards"`

---

### Task 10: MCP entry point and dispatch

**Files:**
- Create: `src/zaptec_mcp_server/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `tool_definitions() -> list[Tool]`, `async dispatch(tools: ZaptecTools, name: str, arguments: dict) -> Any`, `main()`.

- [ ] **Step 1: Write failing tests**

`tests/test_main.py`:

```python
from __future__ import annotations

import json
from typing import Any

import pytest

from zaptec_mcp_server.__main__ import dispatch, tool_definitions
from zaptec_mcp_server.utils.errors import ZaptecGuardError


class StubTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_status(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get_status", kw))
        return {"ok": 1}

    async def get_installation(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get_installation", kw))
        return {}

    async def get_charge_history(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get_charge_history", kw))
        return {}

    async def pause_charging(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("pause_charging", kw))
        return {}

    async def resume_charging(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("resume_charging", kw))
        return {}

    async def set_available_current(self, amps: float | None, **kw: Any) -> dict[str, Any]:
        self.calls.append(("set_available_current", {"amps": amps, **kw}))
        if kw.get("force"):
            raise ZaptecGuardError("nope", {"seconds_until_allowed": 5})
        return {}


def test_tool_definitions_names_and_schemas() -> None:
    defs = {t.name: t for t in tool_definitions()}
    assert set(defs) == {
        "zaptec_get_status",
        "zaptec_get_installation",
        "zaptec_get_charge_history",
        "zaptec_pause_charging",
        "zaptec_resume_charging",
        "zaptec_set_available_current",
    }
    assert defs["zaptec_set_available_current"].inputSchema["required"] == ["amps"]
    assert "custom" in defs["zaptec_get_charge_history"].inputSchema["properties"]["time_range"]["enum"]
    for t in defs.values():
        assert t.inputSchema["additionalProperties"] is False


async def test_dispatch_routes_arguments() -> None:
    stub = StubTools()
    assert await dispatch(stub, "zaptec_get_status", {"charger_id": "c"}) == {"ok": 1}  # type: ignore[arg-type]
    await dispatch(stub, "zaptec_get_charge_history", {"time_range": "week"})  # type: ignore[arg-type]
    await dispatch(stub, "zaptec_set_available_current", {"amps": 10})  # type: ignore[arg-type]
    await dispatch(stub, "zaptec_set_available_current", {"amps": None})  # type: ignore[arg-type]
    assert stub.calls[0] == ("get_status", {"charger_id": "c"})
    assert stub.calls[1] == ("get_charge_history", {"charger_id": None, "time_range": "week", "start_date": None, "end_date": None})
    assert stub.calls[2] == ("set_available_current", {"amps": 10, "installation_id": None, "force": False})
    assert stub.calls[3]["amps"] is None if isinstance(stub.calls[3], dict) else stub.calls[3][1]["amps"] is None


async def test_dispatch_unknown_tool_and_error_payload() -> None:
    stub = StubTools()
    with pytest.raises(RuntimeError) as info:
        await dispatch(stub, "zaptec_nope", {})  # type: ignore[arg-type]
    assert json.loads(str(info.value))["error_type"] == "ZaptecError"
    with pytest.raises(RuntimeError) as info2:
        await dispatch(stub, "zaptec_set_available_current", {"amps": 1, "force": True})  # type: ignore[arg-type]
    payload = json.loads(str(info2.value))
    assert payload["error_type"] == "ZaptecGuardError"
    assert payload["seconds_until_allowed"] == 5
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement**

`src/zaptec_mcp_server/__main__.py`:

```python
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
                "Installation details: address, timezone, main fuse / max current, available current "
                "and mode, load balancing, authentication, enabled features, circuits and chargers. Read-only."
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
                "Completed charging sessions in a time range (installation-local time) with start, end, "
                "duration and energy in kWh, plus a summary. Cost fields appear only when "
                "ZAPTEC_PRICE_PER_KWH is configured. Read-only."
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
                    "start_date": {"type": "string", "description": "ISO date, required for custom"},
                    "end_date": {"type": "string", "description": "ISO date (inclusive), required for custom"},
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="zaptec_pause_charging",
            description=(
                "CHANGES STATE: pause the running charging session (Zaptec command 506). Only valid while "
                "the charger is in connected_charging; otherwise returns an explanation."
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
                "CHANGES STATE: resume a session that was paused via the app or this server (Zaptec "
                "command 507). Only valid when the charger is connected_finished with final_stop_active; "
                "otherwise returns an explanation."
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
                "CHANGES STATE: set the installation's available charging current in amps (all phases), "
                "or null to reset to the installation maximum. Zaptec recommends at most one change per "
                "15 minutes; the server refuses faster changes unless force=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "amps": {
                        "type": ["number", "null"],
                        "description": "Amps between 0 and the installation max current, or null to reset.",
                    },
                    "installation_id": _INSTALLATION_ID,
                    "force": {"type": "boolean", "default": False},
                },
                "required": ["amps"],
                "additionalProperties": False,
            },
        ),
    ]


async def dispatch(tools: ZaptecTools, name: str, arguments: dict[str, Any]) -> Any:
    a = arguments or {}
    try:
        if name == "zaptec_get_status":
            return await tools.get_status(charger_id=a.get("charger_id"))
        if name == "zaptec_get_installation":
            return await tools.get_installation(installation_id=a.get("installation_id"))
        if name == "zaptec_get_charge_history":
            return await tools.get_charge_history(
                charger_id=a.get("charger_id"),
                time_range=a.get("time_range", "month"),
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
            pass

    async with stdio_server() as (reader, writer):
        runner = asyncio.create_task(server.run(reader, writer, server.create_initialization_options()))
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
```

Fix the awkward last assertion in `test_dispatch_routes_arguments` to `assert stub.calls[3][1]["amps"] is None`.

- [ ] **Step 4: Run all tests, ruff, mypy; smoke-start the server**

```bash
pytest -q && ruff check . && mypy
timeout 5 .venv/bin/python -m zaptec_mcp_server < /dev/null; echo "exit=$?"
```
Expected: tests pass; the server starts, logs "logging in" is NOT printed (login is lazy), and exits when stdin closes.

- [ ] **Step 5: Commit** `git add -A src tests && git commit -m "feat: MCP stdio entry point with six zaptec_* tools"`

---

### Task 11: Docs, packaging metadata, CI, integration tests

**Files:**
- Create: `README.md` (replace placeholder), `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `claude_desktop_config_snippet.json`, `manifest.json`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `scripts/probe.py`, `tests/test_integration.py`

- [ ] **Step 1: Write the files**

`README.md` — sections in this order, modeled on the Vaillant README: title `# unofficialzaptecMCP`; one-paragraph description; bold non-affiliation notice ("This project is not affiliated with, endorsed by, or sponsored by Zaptec AS. 'Zaptec' is a trademark of Zaptec AS, used only to describe what the server connects to."); a disclaimer that the server uses the official public Zaptec cloud API with a personal account and may break if the API changes; **Features** (six tools, with a warning that three change state); **Prerequisites** (Zaptec account with owner rights on the charger, Python 3.10–3.14, Claude Desktop); **Installation** (git clone, venv, `pip install -e .`); **Configuration** (table from Task 2 + note that `pin` is not needed); **Claude Desktop** JSON snippet; **Available Tools** table (name, changes state?, description); **Behaviour and limits** (token caching, rate limits 10 req/s, User-Agent, 15-minute guard, caches 15 s / 5 min / 5 min, failures never cached); **Security** (link SECURITY.md, never commit `.env`); **Development** (`pip install -e '.[dev]'`, `pytest`, `ruff check .`, `mypy`, `pytest -m integration` needs `.env`, fixture capture via `scripts/probe.py` + `scripts/sanitize_fixture.py`); **Credits** (Zaptec API docs https://docs.zaptec.com, custom-components/zaptec and pyzaptec as references, Model Context Protocol, unofficialMCP4Vaillant / polestar-mcp as pattern references); **License** MIT.

`claude_desktop_config_snippet.json`:

```json
{
  "mcpServers": {
    "unofficial-zaptec-mcp": {
      "command": "/absolute/path/to/unofficialzaptecMCP/.venv/bin/python",
      "args": ["-m", "zaptec_mcp_server"],
      "env": {
        "ZAPTEC_USERNAME": "your-email@example.com",
        "ZAPTEC_PASSWORD": "your-password",
        "ZAPTEC_PRICE_PER_KWH": "0.30",
        "ZAPTEC_CURRENCY": "EUR",
        "ZAPTEC_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

`manifest.json` — same layout as the Vaillant one: name `unofficial-zaptec-mcp`, version `0.1.0`, the six tools with one-line descriptions, `configuration` with the nine env variables (username/password `sensitive: true`), `entry_point` `{"type": "python_module", "module": "zaptec_mcp_server.__main__", "function": "main"}`.

`CHANGELOG.md` — Keep-a-Changelog header + `## [0.1.0] - 2026-09-22` listing the six tools, token cache, retry policy, guards.

`SECURITY.md` — report via GitHub private vulnerability reporting; credentials only via env/.env; logs redacted; no undocumented endpoints.

`CONTRIBUTING.md` — dev setup, test commands, how to capture and sanitize fixtures (`python scripts/probe.py --dump DIR` then `python scripts/sanitize_fixture.py DIR/chargers.json > tests/fixtures/chargers.json`), and the rule that fixtures must never contain real ids/names.

`.github/workflows/ci.yml` — copy of the Vaillant workflow with matrix `["3.10", "3.11", "3.12", "3.13", "3.14"]`. `.github/dependabot.yml` — pip + github-actions weekly.

`scripts/probe.py`:

```python
"""Manual live probe. Usage: python scripts/probe.py [--dump DIR]

Logs in with the .env credentials, prints a status summary and optionally
dumps raw responses (chargers, state, installation, hierarchy, sessions) to DIR
for later sanitizing with scripts/sanitize_fixture.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zaptec_mcp_server.config import ServerConfig, load_dotenv  # noqa: E402
from zaptec_mcp_server.utils.logging import configure_logging  # noqa: E402
from zaptec_mcp_server.zaptec.client import ZaptecClient  # noqa: E402
from zaptec_mcp_server.zaptec.formatters import format_status  # noqa: E402
from zaptec_mcp_server.zaptec.observations import field  # noqa: E402


async def main(dump: Path | None) -> None:
    load_dotenv()
    cfg = ServerConfig.from_env()
    configure_logging("INFO")
    client = ZaptecClient(cfg)
    try:
        charger = await client.resolve_charger()
        cid = field(charger, "Id")
        state = await client.get_charger_state(cid)
        installation = await client.resolve_installation(charger=charger)
        iid = field(installation, "Id")
        hierarchy = await client.get_hierarchy(iid)
        now = datetime.now(timezone.utc)
        sessions = await client.archived_sessions(start=now - timedelta(days=30), end=now, charger_id=cid)
        print(json.dumps(format_status(charger, state, installation), indent=2))
        print(f"{len(sessions)} sessions in the last 30 days")
        if dump:
            dump.mkdir(parents=True, exist_ok=True)
            (dump / "chargers.json").write_text(json.dumps({"Data": await client.list_chargers()}, indent=1))
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
```

`tests/test_integration.py`:

```python
"""Live tests against the Zaptec cloud. Opt in with `pytest -m integration`; needs .env."""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptec_mcp_server.cache.manager import CacheManager
from zaptec_mcp_server.config import ServerConfig, load_dotenv
from zaptec_mcp_server.server import ZaptecTools
from zaptec_mcp_server.zaptec.client import ZaptecClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def tools() -> ZaptecTools:  # type: ignore[misc]
    load_dotenv(Path(".env"))
    try:
        cfg = ServerConfig.from_env()
    except Exception:  # noqa: BLE001
        pytest.skip("no credentials in environment")
    client = ZaptecClient(cfg)
    yield ZaptecTools(client=client, cache=CacheManager(), cfg=cfg)
    await client.close()


async def test_live_status(tools: ZaptecTools) -> None:
    out = await tools.get_status()
    assert out["charger"]["id"]
    assert out["operating_mode"]["name"] in {
        "unknown", "disconnected", "connected_requesting", "connected_charging", "connected_finished"
    }


async def test_live_installation(tools: ZaptecTools) -> None:
    out = await tools.get_installation()
    assert out["timezone"]
    assert out["circuits"]


async def test_live_history(tools: ZaptecTools) -> None:
    out = await tools.get_charge_history(time_range="month")
    assert out["summary"]["session_count"] >= 0
```

- [ ] **Step 2: Verify**

```bash
pytest -q && ruff check . && mypy
pytest -m integration -q          # live, read-only
python scripts/probe.py           # prints formatted status from the live charger
git status --short | grep -c "\.env$" # must be 0 (ignored)
```

- [ ] **Step 3: Commit** `git add -A && git commit -m "docs: README, packaging metadata, CI and live integration tests"`

---

### Task 12: Claude Desktop wiring and live control check

**Files:**
- Modify: `~/Library/Application Support/Claude/claude_desktop_config.json` (add the `unofficial-zaptec-mcp` entry, keep existing servers)

- [ ] **Step 1: Add the server entry** with the absolute venv python path, `ZAPTEC_USERNAME`/`ZAPTEC_PASSWORD` taken from the project `.env` (values must not be pasted anywhere else), and `ZAPTEC_LOG_LEVEL=INFO`. Back up the existing file to the scratchpad first.

- [ ] **Step 2: Protocol smoke test without Claude Desktop**

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"zaptec_get_status","arguments":{}}}' \
 | timeout 60 .venv/bin/python -m zaptec_mcp_server 2>/dev/null | head -c 4000
```
Expected: three JSON-RPC responses; the third contains `"operating_mode"`.

- [ ] **Step 3: Live control check (only if a vehicle is connected and charging)** — call `zaptec_pause_charging` then, after confirming mode 5 + final_stop_active via `zaptec_get_status`, `zaptec_resume_charging`. Skip and document if no vehicle is charging. Do **not** exercise `zaptec_set_available_current` live in this task; it is verified by unit tests and the user can try it in Claude Desktop.

- [ ] **Step 4: Final commit and summary** — `git status` clean, `git log --oneline`, report to the user: what was built, how to restart Claude Desktop, and what was and was not verified live.

---

## Self-review

- **Spec coverage**: auth/token/retry (T4), rate limit + User-Agent (T4), endpoints + resolution (T5), observations (T3), formatters status/installation (T6), history + cost (T7), read tools + caches (T8), control tools + guards (T9), MCP wiring + error payloads (T10), config incl. `.env` (T2), logging/redaction + cache + timeranges + errors (T1), docs/CI/manifest/snippet/integration/probe/sanitizer (T6, T11), Desktop wiring (T12). `pin` never read (T2 loader only injects; config ignores it). Spec 3.3 mentions `format_command_result` / `format_current_update`; they are inlined in T9 as dict literals instead — acceptable, no separate module needed.
- **Placeholders**: README content is described by section list rather than full prose (deliberate; prose is written in T11). No TBD/TODO.
- **Type consistency**: `field()` from observations used in client, formatters, server; `StateMap` accessor names consistent; `ZaptecTools` ctor kwargs match between T8 tests and T9 tests via `build()`; `FakeApi`/`make_client` shared from `tests/test_client.py`; `CMD_PAUSE`/`CMD_RESUME` defined in T5 and used in T9; `summarize_mode(sm, fallback_code)` defined in T6 and used in T9.
