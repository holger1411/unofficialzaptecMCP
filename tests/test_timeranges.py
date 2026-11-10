from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from zaptec_mcp_server.zaptec.timeranges import resolve_range, validate_custom_dates

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 22, 14, 30, tzinfo=UTC)  # Tuesday, 16:30 Berlin


def test_today() -> None:
    start, end = resolve_range("today", now=NOW, tz=TZ)
    assert start == datetime(2026, 9, 22, 0, 0, tzinfo=TZ)
    assert end == NOW.astimezone(TZ)


def test_yesterday_is_whole_day() -> None:
    start, end = resolve_range("yesterday", now=NOW, tz=TZ)
    assert start == datetime(2026, 9, 21, tzinfo=TZ)
    assert end == datetime(2026, 9, 22, tzinfo=TZ)


def test_week_starts_monday() -> None:
    start, _ = resolve_range("week", now=NOW, tz=TZ)
    assert start == datetime(2026, 9, 21, tzinfo=TZ)


def test_month_and_year() -> None:
    assert resolve_range("month", now=NOW, tz=TZ)[0] == datetime(2026, 9, 1, tzinfo=TZ)
    assert resolve_range("year", now=NOW, tz=TZ)[0] == datetime(2026, 1, 1, tzinfo=TZ)


def test_custom_end_exclusive() -> None:
    start, end = resolve_range(
        "custom", now=NOW, tz=TZ, start_date=date(2026, 9, 1), end_date=date(2026, 9, 3)
    )
    assert start == datetime(2026, 9, 1, tzinfo=TZ)
    assert end == datetime(2026, 9, 4, tzinfo=TZ)


def test_custom_requires_dates_and_unknown_raises() -> None:
    with pytest.raises(ValueError):
        resolve_range("custom", now=NOW, tz=TZ)
    with pytest.raises(ValueError):
        resolve_range("decade", now=NOW, tz=TZ)
    with pytest.raises(ValueError):
        resolve_range("today", now=NOW.replace(tzinfo=None), tz=TZ)


def test_custom_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match=r"end_date .* before start_date"):
        resolve_range(
            "custom", now=NOW, tz=TZ, start_date=date(2026, 9, 3), end_date=date(2026, 9, 1)
        )


def test_custom_single_day_and_max_span() -> None:
    start, end = resolve_range(
        "custom", now=NOW, tz=TZ, start_date=date(2026, 9, 3), end_date=date(2026, 9, 3)
    )
    assert end - start == timedelta(days=1)
    # 366 days inclusive (a whole leap year) is the limit
    resolve_range(
        "custom", now=NOW, tz=TZ, start_date=date(2028, 1, 1), end_date=date(2028, 12, 31)
    )
    with pytest.raises(ValueError, match=r"367 days.*366"):
        resolve_range(
            "custom", now=NOW, tz=TZ, start_date=date(2028, 1, 1), end_date=date(2029, 1, 1)
        )


def test_validate_custom_dates_standalone() -> None:
    validate_custom_dates(date(2026, 1, 1), date(2026, 1, 31))
    with pytest.raises(ValueError):
        validate_custom_dates(None, date(2026, 1, 31))
    with pytest.raises(ValueError):
        validate_custom_dates(date(2026, 2, 1), date(2026, 1, 31))
