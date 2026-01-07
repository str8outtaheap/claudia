"""Shared date/time helpers (CET)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CET_TZ = ZoneInfo("Europe/Paris")


def now_cet() -> datetime:
    return datetime.now(CET_TZ)


def today_cet() -> str:
    return now_cet().date().isoformat()


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    if value == "today":
        return today_cet()
    if value == "yesterday":
        return (now_cet().date() - timedelta(days=1)).isoformat()
    if value == "tomorrow":
        return (now_cet().date() + timedelta(days=1)).isoformat()
    return value
