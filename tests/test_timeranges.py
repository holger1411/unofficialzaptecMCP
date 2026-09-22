from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from zaptec_mcp_server.zaptec.timeranges import resolve_range

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)  # Tuesday, 16:30 Berlin


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
