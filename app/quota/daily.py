"""Daily quota helpers (calendar day in America/Bogota by default)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/Bogota"


def load_zone(tz: str | None) -> ZoneInfo:
    name = (tz or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Bogota")


def today_quota_date(tz: str | None = None) -> date:
    return datetime.now(load_zone(tz)).date()


def next_reset_utc(tz: str | None = None) -> datetime:
    loc = load_zone(tz)
    next_date = datetime.now(loc).date() + timedelta(days=1)
    reset_local = datetime(next_date.year, next_date.month, next_date.day, tzinfo=loc)
    return reset_local.astimezone(timezone.utc)
