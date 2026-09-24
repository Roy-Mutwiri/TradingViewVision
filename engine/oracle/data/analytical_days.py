"""New York analytical days and weeks from UTC M1, never broker D1/W1."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from oracle.config import SessionsConfig
from oracle.models import Bar, Contract, Millis, Price


def parse_boundary(value: str) -> tuple[time, ZoneInfo]:
    clock, zone = value.split()
    parsed = time.fromisoformat(clock)
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise ValueError("Session boundary must be HH:MM in an IANA zone")
    return parsed, ZoneInfo(zone)


def boundary_ms(day: date, clock: time, zone: ZoneInfo) -> int:
    return int(datetime.combine(day, clock, zone).timestamp()) * 1000


def trading_day(t_ms: int, boundary: str = "17:00 America/New_York") -> date:
    clock, zone = parse_boundary(boundary)
    local = datetime.fromtimestamp(t_ms / 1000, UTC).astimezone(zone)
    return local.date() if local.time() >= clock else local.date() - timedelta(days=1)


def trading_day_bounds(t_ms: int, boundary: str) -> tuple[int, int]:
    clock, zone = parse_boundary(boundary)
    day = trading_day(t_ms, boundary)
    return boundary_ms(day, clock, zone), boundary_ms(day + timedelta(days=1), clock, zone)


def trading_week_bounds(t_ms: int, boundary: str) -> tuple[int, int]:
    clock, zone = parse_boundary(boundary)
    local = datetime.fromtimestamp(t_ms / 1000, UTC).astimezone(zone)
    sunday = local.date() - timedelta(days=(local.weekday() + 1) % 7)
    if local.weekday() == 6 and local.time() < clock:
        sunday -= timedelta(days=7)
    return boundary_ms(sunday, clock, zone), boundary_ms(sunday + timedelta(days=7), clock, zone)


class AnalyticalLevels(Contract):
    day_start_ms: Millis
    day_end_ms: Millis
    previous_day_start_ms: Millis
    pdh: Price
    pdl: Price
    pwh: Price
    pwl: Price
    daily_open: Price | None
    midnight_open: Price | None


def analytical_levels(
    bars: list[Bar], as_of_ms: int, sessions: SessionsConfig = SessionsConfig()
) -> AnalyticalLevels:
    if not bars or any(b.tf != "M1" for b in bars):
        raise ValueError("Analytical levels require M1; broker D1/W1 are forbidden")
    if any(b.t_open_ms <= a.t_open_ms for a, b in zip(bars, bars[1:])):
        raise ValueError("Analytical M1 must be ordered and unique")
    day_start, day_end = trading_day_bounds(as_of_ms, sessions.day_boundary)
    grouped: dict[int, list[Bar]] = {}
    for bar in bars:
        if bar.t_open_ms > as_of_ms:
            continue
        start, _ = trading_day_bounds(bar.t_open_ms, sessions.day_boundary)
        grouped.setdefault(start, []).append(bar)
    previous = max((start for start in grouped if start < day_start), default=None)
    if previous is None:
        raise ValueError("Previous trading day M1 history required")
    previous_bars = grouped[previous]
    week_start, _ = trading_week_bounds(as_of_ms, sessions.day_boundary)
    clock, zone = parse_boundary(sessions.day_boundary)
    previous_week_day = datetime.fromtimestamp(week_start / 1000, UTC).astimezone(
        zone
    ).date() - timedelta(days=7)
    previous_week_start = boundary_ms(previous_week_day, clock, zone)
    week_bars = [b for b in bars if previous_week_start <= b.t_open_ms < week_start]
    if not week_bars:
        raise ValueError("Previous trading week M1 history required")
    if bars[0].t_open_ms > previous_week_start:
        raise ValueError("M1 acquisition must cover the entire previous analytical week")
    open_clock, open_zone = parse_boundary(sessions.true_day_open)
    local_now = datetime.fromtimestamp(as_of_ms / 1000, UTC).astimezone(open_zone)
    midnight = boundary_ms(local_now.date(), open_clock, open_zone)
    current_bars = grouped.get(day_start, [])
    midnight_bar = next((b for b in bars if b.t_open_ms == midnight and midnight <= as_of_ms), None)
    return AnalyticalLevels(
        day_start_ms=day_start,
        day_end_ms=day_end,
        previous_day_start_ms=previous,
        pdh=max(b.h for b in previous_bars),
        pdl=min(b.l for b in previous_bars),
        pwh=max(b.h for b in week_bars),
        pwl=min(b.l for b in week_bars),
        daily_open=current_bars[0].o if current_bars else None,
        midnight_open=midnight_bar.o if midnight_bar else None,
    )
