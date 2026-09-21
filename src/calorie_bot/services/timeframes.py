"""Timezone arithmetic.

Everything is stored in UTC (`timestamptz`). Users think in local days. This
module is the only place that converts between the two.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = ZoneInfo("UTC")


def resolve_zone(timezone_name: str | None, fallback: str = "UTC") -> ZoneInfo:
    """Never raise on a bad timezone string — degrade to the fallback."""
    for candidate in (timezone_name, fallback, "UTC"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return UTC


def is_valid_timezone(timezone_name: str) -> bool:
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def local_now(timezone_name: str) -> datetime:
    return datetime.now(tz=resolve_zone(timezone_name))


def local_today(timezone_name: str) -> date:
    return local_now(timezone_name).date()


def day_bounds_utc(day: date, timezone_name: str) -> tuple[datetime, datetime]:
    """Return the half-open UTC interval [start, end) covering a local calendar day."""
    zone = resolve_zone(timezone_name)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def parse_day_offset(offset_days: int, timezone_name: str) -> date:
    """0 = today, -1 = yesterday, 1 = tomorrow, in the user's local calendar."""
    return local_today(timezone_name) + timedelta(days=offset_days)


def to_utc(moment: datetime, timezone_name: str) -> datetime:
    """Attach the user's zone to a naive datetime, then normalise to UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=resolve_zone(timezone_name))
    return moment.astimezone(UTC)


def to_local(moment: datetime, timezone_name: str) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(resolve_zone(timezone_name))
