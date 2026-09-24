"""Build the speaker frame: a projection over ChartFrame state and the Director (docs/ORACLE_BRIDGE.md §1).

Pure functions only. Everything here reads through side-effect-free snapshot accessors that return copies under a
lock (`candidate_service.structure_snapshot` / `liquidity_snapshot`), so building a frame can never disturb the UI
or consume a chart poll the renderer is owed.

Two rules this module exists to enforce:

1. **Units and spellings are normalised once, here.** ORACLE spells it "CHoCH", uses UP/DOWN for structure
   direction while every geometry uses BULLISH/BEARISH, and carries FVG fill as a 0-1 fraction while the dead
   `models.Zone` used 0-100. Getting that wrong is the class of bug that produced "one dollar.ten hundred" in the
   speaker. The wire is: "CHOCH", BULLISH/BEARISH, and fill_pct ALWAYS 0-100.

2. **`hit_rate` and `expectancy` never cross this boundary.** A spoken hit rate is a performance claim about a
   signals community. They are not in the projection, so they cannot be logged, cached or prompted downstream.
   `scoreboard()` drops them explicitly rather than by omission, so the intent survives a refactor.
"""

from __future__ import annotations

from typing import Any

from oracle.ops.speaker_sink import FRAME_VERSION

#: ORACLE's structure vocabulary -> the wire's
_KIND = {"CHoCH": "CHOCH", "BOS": "BOS"}
_DIRECTION = {"UP": "BULLISH", "DOWN": "BEARISH"}
#: never emitted, whatever the numbers say (docs/ORACLE_BRIDGE.md §7)
FORBIDDEN_SCOREBOARD_FIELDS = ("hit_rate", "expectancy")


def _points(level: float, price: float | None, point: float) -> int | None:
    """Signed distance from price, in POINTS, using the instrument's own point size.

    ORACLE computes proximity but discards the distance, so this is computed here - and it must use the same unit
    ORACLE uses everywhere else (`live_chart.py:194`: spread = (ask - bid) / instrument.point). Gold is quoted to
    three decimals on this broker, so a hard-coded 10**2 was out by a factor of ten: the exact class of unit bug
    that produced "one dollar.ten hundred" in the speaker.
    """
    if price is None or not point:
        return None
    return int(round((level - price) / point))


def structure_of(state: Any, tf: str) -> dict[str, Any] | None:
    """`StructureState` -> the wire's bias block. This is the real bias: `RetentionFrame.bias` is a stub."""
    if state is None:
        return None
    event = getattr(state, "last_event", None)
    last: dict[str, Any] | None = None
    if event is not None:
        raw_kind = getattr(event, "kind", "")
        is_mss = bool(getattr(event, "is_mss", False))
        # MSS is not a kind: it is a CHoCH that swept liquidity first. `is_mss` is only ever true when
        # LiquidityEngine.sweep_query is wired into advance_structure - see mss_wired() below.
        kind = "MSS" if (is_mss and raw_kind == "CHoCH") else _KIND.get(raw_kind, raw_kind.upper())
        raw_dir = getattr(event, "direction", "")
        last = {
            "kind": kind,
            "is_mss": is_mss,
            "direction": _DIRECTION.get(raw_dir, raw_dir),
            "level": float(getattr(event, "level", 0.0)),
            "break_close": float(getattr(event, "break_close", 0.0)),
            "t_ms": int(getattr(event, "t_ms", 0)),
            "id": str(getattr(event, "id", "")),
        }
    return {
        "tf": tf,
        "trend": getattr(state, "trend", "UNDEFINED"),
        "trend_since_ms": getattr(state, "trend_since_ms", None),
        "protected_high": getattr(state, "protected_high", None),
        "protected_low": getattr(state, "protected_low", None),
        "last_event": last,
    }


def levels_of(pools: list[Any], weekly_open: float | None, price: float | None, point: float = 0.01) -> list[dict[str, Any]]:
    """Named liquidity pools -> levels. `geometry.name` ("PDH", "ASIA H", ...) is the provenance the speaker
    phrases from; no English is emitted here because ORACLE ships seven languages."""
    out: list[dict[str, Any]] = []
    for pool in pools:
        geometry = getattr(pool, "geometry", None)
        if geometry is None:
            continue
        level = float(getattr(geometry, "level", 0.0))
        out.append(
            {
                "name": str(getattr(geometry, "name", "")),
                "price": level,
                "side": getattr(geometry, "side", ""),
                "state": getattr(pool, "state", "FRESH"),
                "named": bool(getattr(pool, "named", False)),
                "distance_points": _points(level, price, point),
                "swept_ms": getattr(pool, "swept_ms", None),
            }
        )
    if weekly_open:
        out.append(
            {
                "name": "WEEKLY OPEN",
                "price": float(weekly_open),
                "side": "OPEN",
                "state": "FRESH",
                "named": True,
                "distance_points": _points(float(weekly_open), price, point),
                "swept_ms": None,
            }
        )
    out.sort(key=lambda row: abs(row["distance_points"]) if row["distance_points"] is not None else 1 << 30)
    return out


def scoreboard_of(board: Any) -> dict[str, Any]:
    """Activity facts only. hit_rate and expectancy are dropped here, deliberately and by name."""
    today = getattr(board, "today", None)
    if today is None:
        return {}
    projection = {
        "produced": int(getattr(today, "produced", 0)),
        "triggered": int(getattr(today, "triggered", 0)),
        "resolved": int(getattr(today, "resolved", 0)),
        "scratch": int(getattr(today, "scratch", 0)),
        "cancelled": int(getattr(today, "cancelled", 0)),
        "never_triggered": int(getattr(today, "never_triggered", 0)),
        "window": str(getattr(board, "today_label", "")),
    }
    for banned in FORBIDDEN_SCOREBOARD_FIELDS:
        projection.pop(banned, None)  # belt and braces: they were never added, and cannot survive a refactor
    return projection


def mss_wired(pools: list[Any]) -> bool:
    """True when the sweep->MSS link is actually live for this timeframe.

    `StructureEvent.is_mss` is only ever set when `LiquidityEngine.sweep_query` reaches `advance_structure`;
    otherwise `order_blocks.py:315` substitutes the `no_sweep` stub and the flag is permanently False. A
    silently-always-False flag would have the speaker teaching a distinction the engine never makes.

    `candidates/lifecycle.py` passes `self.liquidity.sweep_query if self.liquidity else None` at all five call
    sites, and the same liquidity engine is what produces the pools in `liquidity_views`. So pools present for a
    timeframe means the engine ran, which means the query was wired. Inferred rather than introspected, because
    the engine object is not reachable from a read-only snapshot - and stated on the wire so the speaker can
    refuse to say "MSS" when it is false.
    """
    return bool(pools)


def session_of(now_ms: int, intervals: list[Any], market_closed: bool, next_open_ms: int | None) -> dict[str, Any]:
    """Which session we are in. ORACLE has no session-state object (`smc/killzones.py` is a Phase-2 stub); it only
    buckets M1 bars into per-session pools. So this is computed from `config/session-definitions.json` windows."""
    name, opened = "BETWEEN", None
    for interval in intervals:
        start, end = int(getattr(interval, "start_ms", 0)), int(getattr(interval, "end_ms", 0))
        if start <= now_ms < end:
            name, opened = str(getattr(interval, "key", "")), start
            break
    if market_closed:
        name = "CLOSED"
    return {"name": name, "opened_ms": opened, "next_open_ms": next_open_ms, "market_closed": bool(market_closed)}


def build_frame(
    *,
    seq: int,
    now_ms: int,
    tf: str,
    bid: float | None,
    ask: float | None,
    tick_ms: int | None,
    quality: Any,
    next_close_ms: int | None,
    bar_duration_ms: int | None,
    structure_state: Any,
    pools: list[Any],
    weekly_open: float | None,
    retention: Any,
    intervals: list[Any],
    market_closed: bool,
    next_open_ms: int | None,
    point: float = 0.01,
) -> dict[str, Any]:
    """Assemble one speaker frame. Pure: every argument is already a copy taken under the owner's lock."""
    price: dict[str, Any] | None = None
    mid: float | None = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        price = {
            "bid": float(bid),
            "ask": float(ask),
            "spread_points": int(round((ask - bid) * 100)),
            "t_ms": int(tick_ms or now_ms),
        }
        mid = (float(bid) + float(ask)) / 2

    hook = getattr(retention, "hook", None)
    scoreboard = scoreboard_of(getattr(retention, "scoreboard", None))
    return {
        "v": FRAME_VERSION,
        "seq": seq,
        "at_ms": int(now_ms),
        "symbol": "XAUUSD",
        "tf": tf,
        "price": price,
        "quality": {
            "state": getattr(quality, "state", "NO_DATA"),
            "staleness_ms": int(getattr(quality, "staleness_ms", 0)),
            "spread_points": float(getattr(quality, "spread_points", 0.0)),
        }
        if quality is not None
        else None,
        "next_close_ms": next_close_ms,
        "bar_duration_ms": bar_duration_ms,
        "structure": structure_of(structure_state, tf),
        "mss_detection": mss_wired(pools),
        "levels": levels_of(pools, weekly_open, mid, point),
        "point": point,
        "session": session_of(int(now_ms), intervals, market_closed, next_open_ms),
        "scoreboard": scoreboard,
        "hook": {
            "kind": getattr(hook, "kind", ""),
            "countdown_ms": int(getattr(hook, "countdown_ms", 0)),
            "ends_ms": int(getattr(hook, "ends_ms", 0)),
        }
        if hook is not None
        else None,
    }
