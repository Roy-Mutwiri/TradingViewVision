"""The ribbon and analytical session levels share one session definition file."""

import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from oracle.data.analytical_days import boundary_ms
from oracle.models import Contract

DEFINITIONS = json.loads(
    (Path(__file__).resolve().parents[3] / "config/session-definitions.json").read_text()
)


class SessionInterval(Contract):
    name: str
    key: str
    start_ms: int
    end_ms: int


def session_intervals(t_ms: int) -> tuple[SessionInterval, ...]:
    """Intervals for the UTC date displayed by the existing 24-hour ribbon."""
    day = datetime.fromtimestamp(t_ms / 1000, UTC).date()
    result = []
    for spec in DEFINITIONS:
        zone = ZoneInfo(spec["zone"])
        # Select the local date whose open lies on this ribbon's UTC date.
        local_day = day
        opening = boundary_ms(local_day, time(spec["open"]), zone)
        if datetime.fromtimestamp(opening / 1000, UTC).date() < day:
            local_day += timedelta(days=1)
        elif datetime.fromtimestamp(opening / 1000, UTC).date() > day:
            local_day -= timedelta(days=1)
        result.append(
            SessionInterval(
                name=spec["name"],
                key=spec["key"],
                start_ms=boundary_ms(local_day, time(spec["open"]), zone),
                end_ms=boundary_ms(local_day, time(spec["close"]), zone),
            )
        )
    return tuple(result)
