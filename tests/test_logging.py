import logging

import pytest

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


def test_configure_logging_uses_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    redactor = configure_logging("DEBUG")
    redactor.add("secretvalue")
    logging.getLogger("x").info("token secretvalue")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert REDACTED in captured.err
