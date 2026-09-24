"""Audit a frozen call ledger against stored BID M1 without changing outcomes."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics as stat
from collections import Counter
from pathlib import Path

import duckdb
from oracle.analysis.ledger import CallLedger
from oracle.analysis.scoring import statistics
from oracle.models import Bar, timeframe_ms


def median(values: list[float]) -> float | None:
    return stat.median(values) if values else None


def histogram(values: list[float]) -> dict[str, int]:
    edges = ((1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, math.inf))
    return {
        f"{lo:g}-{hi:g}" if math.isfinite(hi) else f"{lo:g}＋":
        sum(lo <= value < hi for value in values)
        for lo, hi in edges
    }


def state_table(rows: list[object]) -> dict[str, object]:
    calls = [row.call for row in rows]  # type: ignore[attr-defined]
    scored = [call for call in calls if call.state in {"WIN", "LOSS"}]
    stats = statistics(rows)  # type: ignore[arg-type]
    returns = [call.reward_r if call.state == "WIN" else -1.0 for call in scored]
    return {
        "produced": len(calls),
        "states": dict(sorted(Counter(call.state for call in calls).items())),
        "triggered": sum(call.trigger_price is not None or call.state in {"ACTIVE", "WIN", "LOSS", "SCRATCH"} for call in calls),
        "resolved": len(scored),
        "hit_rate": stats.hit_rate,
        "expectancy_r": stats.expectancy,
        "average_realized_r": sum(returns) / len(returns) if returns else None,
    }


def analyse(ledger_path: Path, database: Path, output: Path, split: dict[str, object]) -> dict[str, object]:
    ledger = CallLedger(ledger_path)
    rows = ledger.rows
    with duckdb.connect(str(database), read_only=True) as db:
        raw = db.execute(
            "select payload from bars where broker='exness' and tf='M1' and source='mt5' order by t"
        ).fetchall()
    minutes = [Bar.model_validate_json(item[0]) for item in raw]
    minute_times = [bar.t_open_ms for bar in minutes]
    activated_at: dict[str, int] = {}
    for event in ledger.events:
        if (
            event.call.trigger_price is not None
            or event.call.state in {"ACTIVE", "WIN", "LOSS", "SCRATCH"}
        ) and event.call_id not in activated_at:
            activated_at[event.call_id] = event.at_ms

    calls = [row.call for row in rows]
    triggered = [call for call in calls if call.id in activated_at]
    winners = [call for call in triggered if call.state == "WIN"]
    losers = [call for call in triggered if call.state == "LOSS"]
    quoted = [call.reward_r for call in calls]
    fill_bars = [
        (activated_at[call.id] - call.created_ms) / timeframe_ms(call.timeframe or "M15")
        for call in triggered
    ]
    never_distances: list[float] = []
    for call in calls:
        if call.state != "NEVER_TRIGGERED":
            continue
        lo = bisect.bisect_left(minute_times, call.eval_from_ms)
        hi = bisect.bisect_left(minute_times, call.eval_to_ms)
        distances = [
            call.entry_lo - bar.h if bar.h < call.entry_lo
            else bar.l - call.entry_hi if bar.l > call.entry_hi
            else 0.0
            for bar in minutes[lo:hi]
        ]
        if distances:
            never_distances.append(min(distances))

    by_tf: dict[str, object] = {}
    for timeframe in ("M5", "M15", "H1", "H4"):
        selected = [row for row in rows if row.call.timeframe == timeframe]
        by_tf[timeframe] = state_table(selected)
    cancellations = Counter(row.cancellation_reason or "UNSPECIFIED" for row in rows if row.call.state == "CANCELLED")
    result = {
        "methodology": split,
        "overall": state_table(rows),
        "by_timeframe": by_tf,
        "cancellations": dict(sorted(cancellations.items())),
        "quoted_r": {"histogram": histogram(quoted), "median": median(quoted), "count": len(quoted)},
        "winner_realized_r": {
            "values": [call.reward_r for call in winners],
            "median": median([call.reward_r for call in winners]),
        },
        "excursions": {
            "loser_mfe_median_r": median([call.mfe for call in losers if call.mfe is not None]),
            "loser_mae_median_r": median([call.mae for call in losers if call.mae is not None]),
            "winner_mfe_median_r": median([call.mfe for call in winners if call.mfe is not None]),
            "winner_mae_median_r": median([call.mae for call in winners if call.mae is not None]),
            "triggered_calls": len(triggered),
        },
        "time_to_fill": {
            "count": len(fill_bars),
            "median_bars": median(fill_bars),
            "histogram_bars": {
                "0-1": sum(0 <= value <= 1 for value in fill_bars),
                "1-3": sum(1 < value <= 3 for value in fill_bars),
                "3-6": sum(3 < value <= 6 for value in fill_bars),
                "6-9": sum(6 < value <= 9 for value in fill_bars),
                "9-12": sum(9 < value <= 12 for value in fill_bars),
            },
        },
        "never_triggered": {
            "count": len(never_distances),
            "closest_distance_points_median": median(never_distances),
            "closest_distance_points": never_distances,
        },
        "direction_mismatch_definition": (
            "OB direction differs from that same timeframe's confirmed structure trend; "
            "HTF zones are not consulted by this gate, so counter-trend entries into an HTF zone are rejected."
        ),
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--side", required=True)
    parser.add_argument("--from-ms", required=True, type=int)
    parser.add_argument("--to-ms", required=True, type=int)
    parser.add_argument("--oos-from-ms", required=True, type=int)
    parser.add_argument("--oos-to-ms", type=int)
    args = parser.parse_args()
    report = analyse(args.ledger, args.database, args.output, {
        "side": args.side,
        "from_ms": args.from_ms,
        "to_ms": args.to_ms,
        "sealed_out_of_sample": {"from_ms": args.oos_from_ms, "to_ms": args.oos_to_ms, "run": False},
    })
    print(json.dumps(report, indent=2))
