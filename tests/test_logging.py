import logging
import sys

import pytest

from zaptec_mcp_server.utils.logging import (
    REDACTED,
    RedactingFormatter,
    SecretRedactor,
    configure_logging,
)


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


def test_exception_tracebacks_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    redactor = configure_logging("DEBUG")
    redactor.add("hunter2-secret")
    try:
        raise RuntimeError(
            "login failed for hunter2-secret id=1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d"
        )
    except RuntimeError:
        logging.getLogger("x").exception("boom")
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "hunter2-secret" not in err
    assert "1a2b3c4d" not in err
    assert REDACTED in err


def test_stack_info_is_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    redactor = configure_logging("DEBUG")
    redactor.add("hunter2-secret")

    def leaky_frame(password: str) -> None:
        # The stack dump includes this source line, which contains the literal below.
        logging.getLogger("x").info("where am I", stack_info=True)  # hunter2-secret

    leaky_frame("x")
    err = capsys.readouterr().err
    assert "Stack (most recent call last)" in err
    assert "leaky_frame" in err
    assert "hunter2-secret" not in err
    assert REDACTED in err  # the dumped source line was scrubbed, not just absent


def test_redacting_formatter_scrubs_whole_output() -> None:
    r = SecretRedactor()
    r.add("hunter2-secret")
    fmt = RedactingFormatter("%(name)s %(message)s", r)
    try:
        raise ValueError("hunter2-secret")
    except ValueError:
        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "msg", None, sys.exc_info())
    out = fmt.format(rec)
    assert "hunter2-secret" not in out
    assert "ValueError" in out
