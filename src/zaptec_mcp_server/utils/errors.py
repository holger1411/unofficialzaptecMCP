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


class ZaptecConfigError(ZaptecError, ValueError):
    """Invalid configuration (environment variables, env file). Fatal at startup."""


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
