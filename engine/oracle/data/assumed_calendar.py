"""Explicitly assumed UTC template, used only while observations are pending."""

from datetime import UTC, datetime, timedelta


def assumed_closed(t_ms: int) -> bool:
    t = datetime.fromtimestamp(t_ms / 1000, UTC)
    minute = t.hour * 60 + t.minute
    # Assertion tolerances from the operator's schedule: Fri/Sun 21:00 ±60m,
    # daily maintenance 21:00–22:00 ±30m. Never excuse a hole mid-session.
    return (
        t.weekday() == 5
        or (t.weekday() == 4 and minute >= 20 * 60)
        or (t.weekday() == 6 and minute < 22 * 60)
        or (t.weekday() < 5 and 20 * 60 + 30 <= minute < 22 * 60 + 30)
    )


def assumed_explains(start_ms: int, end_ms: int) -> bool:
    cursor = start_ms
    while cursor < end_ms:
        if not assumed_closed(cursor):
            return False
        t = datetime.fromtimestamp(cursor / 1000, UTC)
        day = t.replace(hour=0, minute=0, second=0, microsecond=0)
        if t.weekday() >= 5 or t.weekday() == 4 and t.hour >= 20:
            opens = day + timedelta(days=(6 - t.weekday()) % 7, hours=22)
        else:
            opens = day + timedelta(hours=22, minutes=30)
        cursor = int(opens.timestamp()) * 1000
    return True
