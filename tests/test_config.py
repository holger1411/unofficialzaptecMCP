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
    monkeypatch.delenv("pin", raising=False)
    parsed = load_dotenv(env_file)
    assert parsed["ZAPTEC_USERNAME"] == "file@example.com"
    assert os.environ["ZAPTEC_USERNAME"] == "env@example.com"
    assert os.environ["ZAPTEC_PASSWORD"] == "pw"
    assert os.environ["ZAPTEC_CURRENCY"] == "NOK"
    assert "pin" in parsed


def test_load_dotenv_missing_file(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "nope") == {}
