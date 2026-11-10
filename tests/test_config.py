import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from zaptec_mcp_server.config import (
    ServerConfig,
    env_file_permission_warning,
    load_dotenv,
    resolve_env_file,
)
from zaptec_mcp_server.utils.errors import ZaptecAuthError, ZaptecConfigError

BASE = {"ZAPTEC_USERNAME": "me@example.com", "ZAPTEC_PASSWORD": "secret-pw"}


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """load_dotenv writes into os.environ directly; undo that after each test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


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


def test_load_dotenv_quoted_value_keeps_inner_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('ZAPTEC_PASSWORD="  pw with spaces  "\n')
    monkeypatch.delenv("ZAPTEC_PASSWORD", raising=False)
    assert load_dotenv(env_file)["ZAPTEC_PASSWORD"] == "  pw with spaces  "


# -- password ---------------------------------------------------------------


def test_password_not_stripped_but_username_is() -> None:
    cfg = ServerConfig.from_env({"ZAPTEC_USERNAME": "  me@example.com ", "ZAPTEC_PASSWORD": " pw "})
    assert cfg.username == "me@example.com"
    assert cfg.password == " pw "


@pytest.mark.parametrize("pw", ["", "   ", "\t\n"])
def test_blank_password_is_missing(pw: str) -> None:
    with pytest.raises(ZaptecAuthError):
        ServerConfig.from_env({"ZAPTEC_USERNAME": "me@example.com", "ZAPTEC_PASSWORD": pw})


# -- base URL ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.zaptec.com", "https://api.zaptec.com"),
        (" HTTPS://api.example.org/ ", "HTTPS://api.example.org"),
        ("https://api.example.org:8443/base/", "https://api.example.org:8443/base"),
        ("http://localhost", "http://localhost"),
        ("http://localhost:9999/", "http://localhost:9999"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("http://[::1]:8080", "http://[::1]:8080"),
        ("http://LOCALHOST:1", "http://LOCALHOST:1"),
    ],
)
def test_base_url_accepted(raw: str, expected: str) -> None:
    assert ServerConfig.from_env({**BASE, "ZAPTEC_API_BASE_URL": raw}).api_base_url == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://anything",
        "http://api.zaptec.com",
        "http://localhost.evil.com",
        "http://127.0.0.1.evil.com",
        "http://user@evil.com",
        "http://localhost@evil.com",
        "https://me:pw@api.zaptec.com",
        "https://api.zaptec.com?x=1",
        "https://api.zaptec.com#frag",
        "https://api.zaptec.com:notaport",
        "ftp://api.zaptec.com",
        "api.zaptec.com",
        "https://",
        "https:///path",
        "//api.zaptec.com",
    ],
)
def test_base_url_rejected(raw: str) -> None:
    with pytest.raises(ZaptecConfigError, match="ZAPTEC_API_BASE_URL"):
        ServerConfig.from_env({**BASE, "ZAPTEC_API_BASE_URL": raw})


def test_base_url_error_does_not_echo_credentials_in_userinfo() -> None:
    with pytest.raises(ZaptecConfigError) as info:
        ServerConfig.from_env({**BASE, "ZAPTEC_API_BASE_URL": "http://me:hunter22@evil.com"})
    assert "hunter22" not in str(info.value)


# -- log level --------------------------------------------------------------


@pytest.mark.parametrize("level", ["debug", "INFO", " warning ", "Error", "CRITICAL"])
def test_log_level_accepted(level: str) -> None:
    cfg = ServerConfig.from_env({**BASE, "ZAPTEC_LOG_LEVEL": level})
    assert cfg.log_level == level.strip().upper()


@pytest.mark.parametrize("level", ["verbose", "TRACE", "10", "NOTSET"])
def test_log_level_rejected(level: str) -> None:
    with pytest.raises(ZaptecConfigError, match="ZAPTEC_LOG_LEVEL"):
        ServerConfig.from_env({**BASE, "ZAPTEC_LOG_LEVEL": level})


def test_config_errors_are_value_errors() -> None:
    assert issubclass(ZaptecConfigError, ValueError)
    with pytest.raises(ZaptecConfigError):
        ServerConfig.from_env({**BASE, "ZAPTEC_PRICE_PER_KWH": "cheap"})


# -- env file location ------------------------------------------------------


def test_env_file_defaults_to_cwd_dotenv() -> None:
    assert resolve_env_file({}) == Path(".env")
    assert resolve_env_file({"ZAPTEC_ENV_FILE": "  "}) == Path(".env")


def test_env_file_explicit(tmp_path: Path) -> None:
    env_file = tmp_path / "zaptec.env"
    env_file.write_text("X=1\n")
    assert resolve_env_file({"ZAPTEC_ENV_FILE": str(env_file)}) == env_file


def test_env_file_explicit_missing_fails(tmp_path: Path) -> None:
    with pytest.raises(ZaptecConfigError, match="ZAPTEC_ENV_FILE"):
        resolve_env_file({"ZAPTEC_ENV_FILE": str(tmp_path / "missing.env")})
    with pytest.raises(ZaptecConfigError, match="ZAPTEC_ENV_FILE"):
        resolve_env_file({"ZAPTEC_ENV_FILE": str(tmp_path)})  # a directory


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
@pytest.mark.parametrize(("mode", "warn"), [(0o600, False), (0o640, True), (0o604, True)])
def test_env_file_permission_warning(tmp_path: Path, mode: int, warn: bool) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ZAPTEC_PASSWORD=topsecret\n")
    env_file.chmod(mode)
    message = env_file_permission_warning(env_file)
    if warn:
        assert message is not None
        assert str(env_file) in message
        assert "topsecret" not in message
    else:
        assert message is None


def test_env_file_permission_warning_missing_file(tmp_path: Path) -> None:
    assert env_file_permission_warning(tmp_path / "nope") is None
