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
    """Logging filter that scrubs secrets and identifier-like patterns."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def add(self, secret: str | None) -> None:
        """Register a secret to redact. Ignored if too short to be safe."""
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
    """Configure the root logger to write to stderr through the redactor."""
    redactor = SecretRedactor()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(redactor)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # httpx logs every request at INFO; keep our own INFO output readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return redactor
