"""BID analysis accountability: a loss pays -1R; no forecast probabilities."""

from oracle.analysis.contracts import CallBoard, CallRow, CallStats
from oracle.data.analytical_days import trading_day

TERMINAL = {"WIN", "LOSS", "SCRATCH", "NEVER_TRIGGERED", "VOID_DATA", "CANCELLED"}


def statistics(rows: list[CallRow]) -> CallStats:
    counts = {name: 0 for name in (
        "produced", "triggered",
        "wins", "losses", "scratch", "never_triggered", "void_data", "cancelled",
        "pending", "active", "ambiguous", "resolved", "gap_skipped",
    )}
    returns: list[float] = []
    for row in rows:
        call = row.call
        counts["produced"] += 1
        if call.trigger_price is not None or call.state in {"ACTIVE", "WIN", "LOSS", "SCRATCH"}:
            counts["triggered"] += 1
        key = {"WIN": "wins", "LOSS": "losses"}.get(call.state, call.state.lower())
        counts[key] += 1
        if call.state in TERMINAL:
            counts["resolved"] += 1
        if row.ambiguous:
            counts["ambiguous"] += 1
        if call.gap_skipped:
            counts["gap_skipped"] += 1
        if call.state == "WIN":
            returns.append(call.reward_r)
        elif call.state == "LOSS":
            returns.append(-1.0)
    denominator = counts["wins"] + counts["losses"]
    return CallStats(**counts,
                     hit_rate=counts["wins"] / denominator if denominator else None,
                     expectancy=sum(returns) / len(returns) if returns else None)


def board(rows: list[CallRow], now_ms: int, boundary: str = "17:00 America/New_York") -> CallBoard:
    day = trading_day(now_ms, boundary).isoformat()
    completed = [row for row in rows if row.call.state in TERMINAL]
    completed.sort(key=lambda row: (row.call.resolved_ms or 0, row.call.id))
    today = [row for row in completed if row.call.resolved_ms is not None
             and trading_day(row.call.resolved_ms, boundary).isoformat() == day]
    label = "TODAY · from 17:00 NY" if boundary == "17:00 America/New_York" else f"TODAY · from {boundary}"
    return CallBoard(rows=rows, today=statistics(today),
                     last_20=statistics(completed[-20:]), all_time=statistics(rows), today_label=label,
                     today_trading_day=day)
