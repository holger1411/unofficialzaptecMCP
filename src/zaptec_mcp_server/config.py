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
        password = e.get("ZAPTEC_PASSWORD", "").strip()
        if not username or not password:
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
            log_level=(e.get("ZAPTEC_LOG_LEVEL") or "INFO").strip().upper(),
            api_base_url=(e.get("ZAPTEC_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
        )
