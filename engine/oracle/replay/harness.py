"""Fail closed on unexplained gaps, including leading/trailing intervals."""

from collections import Counter

from oracle.data.calendar import TradingCalendar
from oracle.models import Bar, timeframe_ms


def replay_proof(
    bars: list[Bar], calendar: TradingCalendar, start_ms: int, end_ms: int
) -> dict[str, int]:
    if end_ms - start_ms < 30 * 86400000:
        raise ValueError("Proof requires at least 30 days")
    if not calendar.valid_from_ms <= start_ms < end_ms <= calendar.valid_to_ms:
        raise ValueError("Calendar does not cover proof window")
    counts: Counter[str] = Counter()
    for tf in sorted({b.tf for b in bars}):
        series = [b for b in bars if b.tf == tf]
        step = timeframe_ms(series[0].tf)
        if any(b.source != "mt5" or not b.complete for b in series):
            raise ValueError("Proof requires complete pure-MT5 bars")
        if any(b.t_open_ms <= a.t_open_ms for a, b in zip(series, series[1:])):
            raise ValueError("Duplicate/out-of-order bars")
        actual = {b.t_open_ms for b in series if start_ms <= b.t_open_ms < end_ms}
        for t in range(start_ms, end_ms, step):
            if t not in actual and not calendar.explains(t, min(t + step, end_ms)):
                raise ValueError(f"Unexplained {tf} gap at {t}")
        counts[tf] = len(actual)
    if not counts.get("M5"):
        raise ValueError("M5 history required")
    return dict(counts)
