from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from zaptec_mcp_server import __main__ as entry
from zaptec_mcp_server.config import ServerConfig

PREFIX = "unofficial-zaptec-mcp: configuration error: "


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run in an empty CWD (never the repo's real .env) with no ZAPTEC_* variables.

    load_dotenv writes into os.environ directly, so restore it wholesale afterwards.
    """
    saved = dict(os.environ)
    for key in [k for k in os.environ if k.startswith("ZAPTEC_")]:
        del os.environ[key]
    monkeypatch.chdir(tmp_path)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _write_env(path: Path, **values: str) -> Path:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    path.chmod(0o600)
    return path


def _run_main(capsys: pytest.CaptureFixture[str]) -> tuple[int | str | None, str, str]:
    with pytest.raises(SystemExit) as info:
        entry.main()
    captured = capsys.readouterr()
    return info.value.code, captured.out, captured.err


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({}, "ZAPTEC_USERNAME and ZAPTEC_PASSWORD are required"),
        ({"ZAPTEC_PRICE_PER_KWH": "cheap"}, "ZAPTEC_PRICE_PER_KWH"),
        ({"ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL": "-5"}, "ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL"),
        ({"ZAPTEC_API_BASE_URL": "http://anything"}, "ZAPTEC_API_BASE_URL"),
        ({"ZAPTEC_LOG_LEVEL": "verbose"}, "ZAPTEC_LOG_LEVEL"),
        ({"ZAPTEC_ENV_FILE": "/definitely/not/here.env"}, "ZAPTEC_ENV_FILE"),
    ],
)
def test_config_errors_exit_2_with_one_stderr_line(
    env: dict[str, str], needle: str, capsys: pytest.CaptureFixture[str]
) -> None:
    creds = {} if not env else {"ZAPTEC_USERNAME": "me@example.com", "ZAPTEC_PASSWORD": "pw-123"}
    os.environ.update({**creds, **env})
    code, out, err = _run_main(capsys)
    assert code == 2
    assert out == ""
    assert err.startswith(PREFIX)
    assert err.endswith("\n")
    assert err.count("\n") == 1
    assert needle in err
    assert "Traceback" not in err
    assert "pw-123" not in err


def test_explicit_env_file_is_loaded_instead_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_env(tmp_path / ".env", ZAPTEC_USERNAME="cwd@example.com", ZAPTEC_PASSWORD="cwd-pw")
    elsewhere = tmp_path / "conf"
    elsewhere.mkdir()
    chosen = _write_env(
        elsewhere / "zaptec.env", ZAPTEC_USERNAME="file@example.com", ZAPTEC_PASSWORD="file-pw"
    )
    os.environ["ZAPTEC_ENV_FILE"] = str(chosen)
    seen: list[tuple[ServerConfig, Path]] = []

    async def fake_run(cfg: ServerConfig, env_file: Path) -> None:
        seen.append((cfg, env_file))

    monkeypatch.setattr(entry, "_run", fake_run)
    entry.main()
    assert capsys.readouterr().out == ""
    [(cfg, env_file)] = seen
    assert env_file == chosen
    assert cfg.username == "file@example.com"
    assert cfg.password == "file-pw"


def test_cwd_env_file_is_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_env(tmp_path / ".env", ZAPTEC_USERNAME="cwd@example.com", ZAPTEC_PASSWORD="cwd-pw")
    seen: list[ServerConfig] = []

    async def fake_run(cfg: ServerConfig, env_file: Path) -> None:
        seen.append(cfg)

    monkeypatch.setattr(entry, "_run", fake_run)
    entry.main()
    assert capsys.readouterr().out == ""
    assert seen[0].username == "cwd@example.com"


def test_keyboard_interrupt_exits_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    os.environ.update({"ZAPTEC_USERNAME": "me@example.com", "ZAPTEC_PASSWORD": "pw-123"})

    async def fake_run(cfg: ServerConfig, env_file: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(entry, "_run", fake_run)
    code, out, _err = _run_main(capsys)
    assert code == 130
    assert out == ""


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
@pytest.mark.parametrize(("mode", "warned"), [(0o600, False), (0o644, True)])
def test_setup_logging_warns_about_loose_env_file_permissions(
    tmp_path: Path, mode: int, warned: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = _write_env(tmp_path / ".env", ZAPTEC_PASSWORD="topsecret-pw")
    env_file.chmod(mode)
    cfg = ServerConfig.from_env(
        {"ZAPTEC_USERNAME": "me@example.com", "ZAPTEC_PASSWORD": "topsecret-pw"}
    )
    redactor = entry._setup_logging(cfg, env_file)
    logging.getLogger("x").info("using topsecret-pw")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "topsecret-pw" not in captured.err
    assert ("readable by group or others" in captured.err) is warned
    assert redactor.scrub("me@example.com") != "me@example.com"
