"""Environment-variable driven configuration (+ minimal .env loader)."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .utils.errors import ZaptecAuthError, ZaptecConfigError

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}
DEFAULT_BASE_URL = "https://api.zaptec.com"
DEFAULT_ENV_FILE = Path(".env")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
# Plain http is only acceptable when the traffic never leaves the machine.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_BASE_URL_RULE = (
    "ZAPTEC_API_BASE_URL must be an https:// URL "
    "(http:// is only allowed for localhost, 127.0.0.1 and ::1)"
)


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
        raise ZaptecConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value < 0:
        raise ZaptecConfigError(f"{name} must not be negative")
    return value


def _log_level(raw: str | None) -> str:
    value = (raw or "").strip().upper() or "INFO"
    if value not in LOG_LEVELS:
        raise ZaptecConfigError(
            f"ZAPTEC_LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, got {raw!r}"
        )
    return value


def _base_url(raw: str | None) -> str:
    """Validate the API base URL. The raw value is never echoed: it may hold credentials."""
    value = (raw or "").strip().rstrip("/") or DEFAULT_BASE_URL
    try:
        parts = urlsplit(value)
        host = parts.hostname
        _ = parts.port  # raises ValueError for a non-numeric or out-of-range port
    except ValueError as exc:
        raise ZaptecConfigError("ZAPTEC_API_BASE_URL is not a valid URL") from exc
    if parts.username is not None or parts.password is not None:
        raise ZaptecConfigError("ZAPTEC_API_BASE_URL must not contain user credentials")
    if "?" in value or "#" in value:
        raise ZaptecConfigError("ZAPTEC_API_BASE_URL must not contain a query or fragment")
    scheme = parts.scheme.lower()
    if scheme not in {"https", "http"}:
        raise ZaptecConfigError(_BASE_URL_RULE)
    if not host:
        raise ZaptecConfigError("ZAPTEC_API_BASE_URL must include a host name")
    if scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise ZaptecConfigError(_BASE_URL_RULE)
    return value


def resolve_env_file(env: Mapping[str, str] | None = None) -> Path:
    """`ZAPTEC_ENV_FILE` if set (it must exist), else `.env` in the current directory."""
    e = os.environ if env is None else env
    raw = e.get("ZAPTEC_ENV_FILE", "").strip()
    if not raw:
        return DEFAULT_ENV_FILE
    path = Path(raw).expanduser()
    if not path.is_file():
        raise ZaptecConfigError(f"ZAPTEC_ENV_FILE={raw!r} does not exist or is not a file")
    return path


def env_file_permission_warning(path: Path) -> str | None:
    """A warning (path only, never contents) if a POSIX env file is group/world readable."""
    if os.name != "posix":
        return None
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if not stat.S_ISREG(mode) or not mode & (stat.S_IRGRP | stat.S_IROTH):
        return None
    shown = path.absolute()
    return f"env file {shown} is readable by group or others; consider: chmod 600 {shown}"


def load_dotenv(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    """Parse KEY=VALUE lines; inject into os.environ without overriding existing keys."""
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
        # Never strip the password: leading/trailing spaces may be part of it.
        password = e.get("ZAPTEC_PASSWORD", "")
        if not username or not password.strip():
            raise ZaptecAuthError("ZAPTEC_USERNAME and ZAPTEC_PASSWORD are required")
        interval = _float(
            e.get("ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL"), "ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL"
        )
        return cls(
            username=username,
            password=password,
            price_per_kwh=_float(e.get("ZAPTEC_PRICE_PER_KWH"), "ZAPTEC_PRICE_PER_KWH"),
            currency=(e.get("ZAPTEC_CURRENCY") or "EUR").strip().upper(),
            default_charger_id=e.get("ZAPTEC_DEFAULT_CHARGER_ID", "").strip() or None,
            min_current_update_interval=900.0 if interval is None else interval,
            cache_enabled=_bool(e.get("ZAPTEC_CACHE_ENABLED"), True),
            log_level=_log_level(e.get("ZAPTEC_LOG_LEVEL")),
            api_base_url=_base_url(e.get("ZAPTEC_API_BASE_URL")),
        )
