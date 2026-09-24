"""Derive closures from observed M1 gaps, with an explicit validity horizon."""

import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from oracle.data.broker_clock import BrokerClock
from oracle.models import Bar, Contract

MINUTE = 60000
WEEK = 7 * 24 * 60 * MINUTE
# Unix epoch Thursday; align weekly phase to Monday.
MONDAY = 4 * 24 * 60 * MINUTE


class Closure(Contract):
    start_ms: int
    end_ms: int
    recurring: bool


class TradingCalendar(Contract):
    canonical_broker: str | None = None
    clock_version: int | None = None
    valid_from_ms: int
    valid_to_ms: int
    closures: tuple[Closure, ...]

    def is_tradeable(self, t_ms: int) -> bool:
        if not self.valid_from_ms <= t_ms < self.valid_to_ms:
            raise ValueError("Outside observed calendar horizon; derive a fresh calendar")
        return not any(c.start_ms <= t_ms < c.end_ms for c in self.closures)

    def next_open(self, t_ms: int) -> int:
        self.is_tradeable(t_ms)
        for c in self.closures:
            if c.start_ms <= t_ms < c.end_ms:
                return c.end_ms
        return t_ms

    def next_close(self, t_ms: int) -> int | None:
        self.is_tradeable(t_ms)
        return next((c.start_ms for c in self.closures if c.start_ms >= t_ms), None)

    def explains(self, start_ms: int, end_ms: int) -> bool:
        if not self.valid_from_ms <= start_ms <= end_ms <= self.valid_to_ms:
            raise ValueError("Outside observed calendar horizon; derive a fresh calendar")
        cursor = start_ms
        for closure in self.closures:
            if closure.end_ms <= cursor:
                continue
            if closure.start_ms > cursor:
                return False
            cursor = max(cursor, closure.end_ms)
            if cursor >= end_ms:
                return True
        return cursor >= end_ms


def derive_calendar(bars: list[Bar], clock: BrokerClock | None = None) -> TradingCalendar:
    if len(bars) < 2 or any(b.tf != "M1" or b.source != "mt5" for b in bars):
        raise ValueError("Calendar requires pure MT5 M1 history")
    if any(b.t_open_ms <= a.t_open_ms for a, b in zip(bars, bars[1:])):
        raise ValueError("Calendar history must be ordered and unique")
    end = bars[-1].t_open_ms + MINUTE
    start = max(bars[0].t_open_ms, end - 180 * 24 * 60 * MINUTE)
    groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for a, b in zip(bars, bars[1:]):
        lo, hi = a.t_open_ms + MINUTE, b.t_open_ms
        if lo >= start and hi - lo > 5 * MINUTE:
            groups[((lo - MONDAY) % WEEK) // MINUTE].append((lo, hi))
    closures = []
    unmatched = []
    for phase, gaps in groups.items():
        first = start + (MONDAY + phase * MINUTE - start) % WEEK
        opportunities = max(1, (end - 1 - first) // WEEK + 1)
        recurring = len({(lo - MONDAY) // WEEK for lo, _ in gaps}) / opportunities >= 0.8
        for lo, hi in gaps:
            if recurring or hi - lo > 4 * 60 * MINUTE:
                closures.append(Closure(start_ms=lo, end_ms=hi, recurring=recurring))
            else:
                unmatched.append((lo, hi))
    # An observed early close can be shorter than four hours (e.g. Labour Day).
    # Recognize only an extension of a measured recurring maintenance closure,
    # ending at the same weekly reopen phase. An arbitrary in-session hole fails.
    regular = [c for c in closures if c.recurring and c.end_ms - c.start_ms <= 4 * 60 * MINUTE]
    for lo, hi in unmatched:
        if any(
            min((hi - c.end_ms) % WEEK, (c.end_ms - hi) % WEEK) <= MINUTE
            and hi - lo > c.end_ms - c.start_ms + 5 * MINUTE
            for c in regular
        ):
            closures.append(Closure(start_ms=lo, end_ms=hi, recurring=False))
    return TradingCalendar(
        canonical_broker=clock.broker if clock else None,
        clock_version=clock.version if clock else None,
        valid_from_ms=start,
        valid_to_ms=end,
        closures=tuple(sorted(closures, key=lambda c: c.start_ms)),
    )


def save_calendar(calendar: TradingCalendar, path: Path) -> None:
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    raw = raw or {}
    previous = raw.get("derived")
    current = calendar.model_dump(mode="json")
    if previous != current:
        logging.getLogger(__name__).warning("Derived session calendar changed")
    raw["derived"] = current
    raw["observed_holidays"] = [
        {
            "date": datetime.fromtimestamp(c.start_ms / 1000, UTC).date().isoformat(),
            "start_ms": c.start_ms,
            "duration_ms": c.end_ms - c.start_ms,
        }
        for c in calendar.closures
        if not c.recurring
    ]
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def local_session_ms(day: str, clock: str, zone: str) -> int:
    return (
        int(datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ZoneInfo(zone)).timestamp())
        * 1000
    )
