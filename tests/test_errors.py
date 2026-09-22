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
