"""Scan observed weekends; align each trading week independently to UTC.

Neither EU nor US transition dates are encoded here. Session shifts require
independent price evidence because session hours alone cannot distinguish a
server-clock change from a change to market hours.
"""

from oracle.data.broker_bar import RawBrokerBar
from oracle.data.broker_clock import BoundaryEvidence, BrokerClock, derive_transitions
from oracle.data.clock_alignment import CANDIDATE_OFFSETS, correlate_offsets
from oracle.data.mt5_feed import UTCFeed

DAY_MS = 86400000


def derive_history_clock(
    raw: list[RawBrokerBar],
    vendor: UTCFeed,
    broker: str,
    expected: tuple[int, ...],
    live_offset_s: int,
    previous: BrokerClock | None = None,
) -> BrokerClock:
    if not raw or any(b.tf != "M1" or not b.complete for b in raw):
        raise ValueError("Historical clock derivation requires closed raw M1 history")
    if any(b.t_broker_ms <= a.t_broker_ms for a, b in zip(raw, raw[1:])):
        raise ValueError("Historical raw bars must be ordered and unique")
    weeks: list[list[RawBrokerBar]] = [[]]
    for bar in raw:
        if weeks[-1] and bar.t_broker_ms - weeks[-1][-1].t_broker_ms > DAY_MS:
            weeks.append([])
        weeks[-1].append(bar)
    evidence: list[BoundaryEvidence] = []
    for week in weeks:
        if len(week) < 500:
            raise ValueError("Every observed trading week needs a 500-bar UTC alignment window")
        # Choose an intraday window, away from weekend edges and maintenance.
        # This is a sampling location, not a session definition or a DST rule.
        index = next(
            (
                i
                for i, b in enumerate(week)
                if b.t_broker_ms % DAY_MS == 7 * 3600000 and len(week) - i >= 500
            ),
            None,
        )
        if index is None:
            index = (len(week) - 500) // 2
        sample = week[index : index + 500]
        reference = vendor.history(
            "M1",
            sample[0].t_broker_ms - max(CANDIDATE_OFFSETS) * 1000,
            sample[-1].t_broker_ms - min(CANDIDATE_OFFSETS) * 1000 + 60000,
        )
        report = correlate_offsets(sample, reference)
        if report.offset_s not in expected:
            raise ValueError(
                "HALTED: independent UTC historical offset outside broker expected set"
            )
        evidence.append(
            BoundaryEvidence(
                t_broker_ms=week[0].t_broker_ms,
                t_utc_ms=week[0].t_broker_ms - report.offset_s * 1000,
            )
        )
    last_offset = (evidence[-1].t_broker_ms - evidence[-1].t_utc_ms) // 1000
    if last_offset != live_offset_s:
        raise ValueError("HALTED: latest historical UTC alignment disagrees with live measurement")
    clock = derive_transitions(broker, tuple(evidence), previous)
    clock.assert_expected(broker, expected)
    return clock
