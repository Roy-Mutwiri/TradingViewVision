
"""History-backed statistics for ORACLE's read-only Book layer.

Every public sentence that uses these figures carries an id, n and date range. The
module reads stored broker bars only; it never mutates engine state and never feeds the
call producer.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from oracle.data.candle_store import CandleStore
from oracle.models import Bar, content_hash

NY = ZoneInfo("America/New_York")
SESSION_DEFS = (
    ("ASIA", ZoneInfo("Asia/Tokyo"), 9, 18),
    ("LONDON", ZoneInfo("Europe/London"), 8, 17),
    ("NY", ZoneInfo("America/New_York"), 8, 17),
)


def _day_key(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, UTC).astimezone(NY)
    if dt.timetz().replace(tzinfo=None) < time(17, 0):
        dt = dt - timedelta(days=1)
    return dt.date().isoformat()


def _slot(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, UTC)
    minute = (dt.minute // 15) * 15
    return f"{dt.hour:02d}:{minute:02d}"


def _session(ms: int) -> str | None:
    dt_utc = datetime.fromtimestamp(ms / 1000, UTC)
    for key, zone, open_hour, close_hour in SESSION_DEFS:
        local = dt_utc.astimezone(zone)
        if open_hour <= local.hour < close_hour:
            return key
    return None


def _pct(num: int, den: int) -> float | None:
    return round(100 * num / den, 1) if den else None


def _table(total: int, counts: Counter[str]) -> dict[str, Any]:
    return {"n": total, "counts": dict(counts), "pct": {k: _pct(v, total) for k, v in counts.items()}}


@dataclass(frozen=True)
class _Daily:
    key: str
    bars: list[Bar]

    @property
    def high(self) -> float:
        return max(b.h for b in self.bars)

    @property
    def low(self) -> float:
        return min(b.l for b in self.bars)

    @property
    def open(self) -> float:
        return self.bars[0].o

    @property
    def close(self) -> float:
        return self.bars[-1].c

    @property
    def range(self) -> float:
        return self.high - self.low


_CACHE: dict[tuple[str, str, int, int], dict[str, Any]] = {}


def _stored_m1(store: CandleStore) -> list[Bar]:
    rows = store.db.execute(
        "SELECT payload FROM bars WHERE broker=? AND tf='M1' ORDER BY t", [store.broker]
    ).fetchall()
    return [Bar.model_validate_json(row[0]) for row in rows]


def compute_history_stats(store: CandleStore, instrument: str = "XAUUSDz") -> dict[str, Any]:
    """Compute deterministic descriptive statistics over all stored M1 history."""
    rows = store.db.execute(
        "SELECT min(t), max(t), count(*) FROM bars WHERE broker=? AND tf='M1'", [store.broker]
    ).fetchone()
    min_t, max_t, count = (int(rows[0] or 0), int(rows[1] or 0), int(rows[2] or 0)) if rows else (0, 0, 0)
    day = _day_key(max_t) if max_t else "none"
    key = (store.path, instrument, count, max_t)
    if key in _CACHE:
        return _CACHE[key]
    cache_path = Path(store.path).with_name(f"book-stats-{instrument}-{day}.json")
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("schema_version") == "book-stats-v2" and cached.get("bar_count") == count and cached.get("data_range", {}).get("end_ms") == max_t:
                _CACHE[key] = cached
                return cached
        except Exception:
            pass

    bars = _stored_m1(store)
    if not bars:
        out = {"id": "stats:empty", "instrument": instrument, "bar_count": 0, "data_range": {"start_ms": 0, "end_ms": 0}, "tables": {}}
        _CACHE[key] = out
        return out

    by_day: dict[str, list[Bar]] = defaultdict(list)
    for b in bars:
        if b.complete:
            by_day[_day_key(b.t_open_ms)].append(b)
    days = [_Daily(k, v) for k, v in sorted(by_day.items()) if len(v) >= 60]
    closed_days = days[:-1] if len(days) > 1 else days
    last20 = closed_days[-20:]
    adr20 = mean([d.range for d in last20]) if last20 else None

    vol_slots: dict[str, list[float]] = defaultdict(list)
    for b in bars:
        vol_slots[_slot(b.t_open_ms)].append(abs(b.c - b.o))
    vol_profile = {k: {"avg_abs_move": round(mean(v), 3), "n": len(v)} for k, v in sorted(vol_slots.items())}

    session_ranges: dict[str, list[float]] = defaultdict(list)
    session_day: dict[tuple[str, str], list[Bar]] = defaultdict(list)
    for b in bars:
        sess = _session(b.t_open_ms)
        if sess:
            session_day[(_day_key(b.t_open_ms), sess)].append(b)
    for (_day, sess), group in session_day.items():
        if group:
            session_ranges[sess].append(max(b.h for b in group) - min(b.l for b in group))
    session_stats = {k: {"avg_range": round(mean(v), 2), "median_range": round(median(v), 2), "n": len(v)} for k, v in session_ranges.items()}

    london_takes: Counter[str] = Counter()
    london_n = 0
    for d in closed_days:
        asia = session_day.get((d.key, "ASIA"), [])
        london = session_day.get((d.key, "LONDON"), [])
        if not asia or not london:
            continue
        london_n += 1
        ah, al = max(b.h for b in asia), min(b.l for b in asia)
        took_h = max(b.h for b in london) > ah
        took_l = min(b.l for b in london) < al
        london_takes["both" if took_h and took_l else "asia_high" if took_h else "asia_low" if took_l else "neither"] += 1

    pdh_pdl = Counter()
    daily_open_returns = 0
    prev: _Daily | None = None
    for d in closed_days[1:]:
        if prev is None:
            prev = d
            continue
        if d.high > prev.high:
            pdh_pdl["PDH"] += 1
        if d.low < prev.low:
            pdh_pdl["PDL"] += 1
        if d.low <= d.open <= d.high:
            daily_open_returns += 1
        prev = d

    sweep_reclaim = Counter()
    sweep_follow = Counter()
    sweep_follow_samples: list[dict[str, Any]] = []
    # Lightweight history-only sweep proxy around previous-day extremes; exact liquidity sweeps live in DecisionLog.
    prev = None
    for d in closed_days[1:]:
        if prev is None:
            prev = d
            continue
        for side, level in (("HIGH", prev.high), ("LOW", prev.low)):
            touched = [i for i, b in enumerate(d.bars) if (b.h > level if side == "HIGH" else b.l < level)]
            if not touched:
                continue
            i = touched[0]
            window = d.bars[i : i + 4]
            reclaim_idx = next(
                (
                    i + j
                    for j, b in enumerate(window)
                    if (b.c < level if side == "HIGH" else b.c > level)
                ),
                None,
            )
            reclaimed = reclaim_idx is not None
            sweep_reclaim["reclaimed" if reclaimed else "accepted"] += 1
            if reclaimed and reclaim_idx is not None and reclaim_idx + 1 < len(d.bars):
                atr = max(0.5, mean([x.h - x.l for x in d.bars[max(0, i - 14) : i + 1]]))
                later = d.bars[reclaim_idx + 1 : min(len(d.bars), reclaim_idx + 61)]
                followed = (min(b.l for b in later) <= level - atr) if side == "HIGH" else (max(b.h for b in later) >= level + atr)
                sweep_follow["follow_1atr" if followed else "no_follow"] += 1
                if len(sweep_follow_samples) < 20:
                    sweep_follow_samples.append(
                        {
                            "day": d.key,
                            "side": side,
                            "level": round(level, 2),
                            "penetration_bar_ms": d.bars[i].t_open_ms,
                            "condition_ms": d.bars[reclaim_idx].t_open_ms,
                            "atr_at_condition": round(atr, 2),
                            "target": round(level - atr if side == "HIGH" else level + atr, 2),
                            "success": followed,
                            "outcome_window_start_ms": later[0].t_open_ms if later else None,
                            "outcome_window_end_ms": later[-1].t_open_ms if later else None,
                        }
                    )
        prev = d

    streak_counts: Counter[str] = Counter()
    streak = 0
    last_dir = 0
    for d in closed_days:
        direction = 1 if d.close > d.open else -1 if d.close < d.open else 0
        if direction == last_dir and direction != 0:
            streak += 1
        else:
            streak = 1 if direction else 0
            last_dir = direction
        if streak >= 3:
            streak_counts["3_up" if direction > 0 else "3_down"] += 1

    model = Counter()
    model_bias = Counter()
    for d in closed_days:
        asia = session_day.get((d.key, "ASIA"), [])
        london = session_day.get((d.key, "LONDON"), [])
        ny = session_day.get((d.key, "NY"), [])
        if not asia or not london or not ny:
            continue
        ar_hi, ar_lo = max(b.h for b in asia), min(b.l for b in asia)
        swept_hi = max(b.h for b in london) > ar_hi
        swept_lo = min(b.l for b in london) < ar_lo
        expanded_up = max(b.h for b in ny) > ar_hi
        expanded_down = min(b.l for b in ny) < ar_lo
        if swept_hi or swept_lo:
            model["asia_london_sweep_ny_expansion"] += 1 if expanded_up or expanded_down else 0
            side = "high" if swept_hi and not swept_lo else "low" if swept_lo and not swept_hi else "both"
            model_bias[f"{side}_then_up" if expanded_up else f"{side}_then_down" if expanded_down else f"{side}_then_none"] += 1

    ranges = [d.range for d in closed_days]
    weekend_gaps = []
    for a, b in zip(closed_days, closed_days[1:], strict=False):
        gap = b.open - a.close
        if abs(gap) >= 1:
            filled = b.low <= a.close <= b.high
            weekend_gaps.append((abs(gap), filled))

    out = {
        "id": content_hash((instrument, min_t, max_t, count, "book-stats-v2")),
        "schema_version": "book-stats-v2",
        "instrument": instrument,
        "bar_count": count,
        "data_range": {"start_ms": min_t, "end_ms": max_t, "days": len(closed_days)},
        "adr20": {"value": round(adr20, 2) if adr20 else None, "n": len(last20), "source_id": "stat:adr20"},
        "volatility_profile": vol_profile,
        "session_stats": session_stats,
        "london_takes_asia": _table(london_n, london_takes),
        "prior_day_levels": {"n": max(0, len(closed_days) - 1), "pdh_taken_pct": _pct(pdh_pdl["PDH"], max(0, len(closed_days) - 1)), "pdl_taken_pct": _pct(pdh_pdl["PDL"], max(0, len(closed_days) - 1)), "daily_open_return_pct": _pct(daily_open_returns, len(closed_days))},
        "sweeps": {
            "reclaim": _table(sum(sweep_reclaim.values()), sweep_reclaim),
            "follow_after_reclaim": _table(sum(sweep_follow.values()), sweep_follow)
            | {
                "definition": {
                    "condition_window": "Previous-day high/low first wick penetration; reclaim must close back inside within the penetration bar plus the next 3 M1 bars.",
                    "condition_known_at": "The close of the first reclaim M1 bar.",
                    "outcome_window": "The 60 M1 bars after the reclaim bar; bars before or including the reclaim bar are excluded.",
                    "success": "After a high sweep reclaim, later low <= swept level - ATR; after a low sweep reclaim, later high >= swept level + ATR.",
                    "already_true_excluded": True,
                    "lookahead_check": "Only bars up to the reclaim close define the condition and ATR; outcome bars start after the condition is known.",
                },
                "samples": sweep_follow_samples,
            },
        },
        "structure": {"BOS": {"follow_pct": None, "n": 0}, "CHoCH": {"follow_pct": None, "n": 0}, "MSS": {"follow_pct": None, "n": 0}},
        "weekend_gaps": {"n": len(weekend_gaps), "median_size": round(median([g for g, _ in weekend_gaps]), 2) if weekend_gaps else None, "fill_pct": _pct(sum(1 for _, f in weekend_gaps if f), len(weekend_gaps))},
        "streaks": {"n": sum(streak_counts.values()), "counts": dict(streak_counts)},
        "daily_model": {"n": sum(model.values()), "shape_pct": _pct(model["asia_london_sweep_ny_expansion"], max(1, len(closed_days))), "direction_after_sweep": dict(model_bias)},
        "range_distribution": {"n": len(ranges), "median": round(median(ranges), 2) if ranges else None},
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass
    _CACHE[key] = out
    return out


