"""Resolve named time ranges (today/yesterday/week/...) in the installation's timezone."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

RangeName = Literal["today", "yesterday", "week", "month", "year", "custom"]


def resolve_range(
    name: str,
    *,
    now: datetime,
    tz: ZoneInfo,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes in `tz` for a named range.

    `end` is exclusive for `custom`/`yesterday` (whole-day ranges) and equal to
    `now` for "running" ranges (today/week/month/year) so totals reflect what
    has happened so far.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now_local = now.astimezone(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if name == "today":
        return today_start, now_local
    if name == "yesterday":
        return today_start - timedelta(days=1), today_start
    if name == "week":
        # ISO week: Monday is weekday 0
        monday = today_start - timedelta(days=now_local.weekday())
        return monday, now_local
    if name == "month":
        return today_start.replace(day=1), now_local
    if name == "year":
        return today_start.replace(month=1, day=1), now_local
    if name == "custom":
        if start_date is None or end_date is None:
            raise ValueError("custom range requires start_date and end_date")
        start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz)
        end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=tz) + timedelta(days=1)
        return start, end
    raise ValueError(f"unknown range: {name!r}")
