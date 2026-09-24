"""Causal confirmed swing structure; wicks define pivots, bodies define breaks.

Consumed levels break once. Protection is the inclusive closed interval extreme,
never a fabricated fractal. New pivots cannot move protection: only a break can.
No indicator trend, tick input, clock dependency or liquidity detector exists here.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from oracle.config import StructureConfig
from oracle.models import Bar, Contract, content_hash, timeframe_ms
from oracle.smc.swing_contracts import Pivot
from oracle.smc.swings import SwingConfig, SwingCursor, advance_swings

Trend = Literal["BULLISH", "BEARISH", "UNDEFINED"]
SweepQuery = Callable[[str, int, int, str], str | None]
logger = logging.getLogger(__name__)


class StructureEvent(Contract):
    id: str
    kind: Literal["BOS", "CHoCH"]
    is_mss: bool = False
    direction: Literal["UP", "DOWN"]
    level: float
    broken_swing_id: str
    broken_swing_idx: int
    break_bar_idx: int
    break_close: float
    timeframe: str
    trend_before: Trend
    trend_after: Trend
    atr_at_break: float
    t_ms: int
    sweep_event_id: str | None = None

    @property
    def sweep_id(self) -> str | None:
        return self.sweep_event_id
    source_bars: tuple[int, ...]
    source_object_ids: tuple[str, ...]


class StructureState(Contract):
    schema_version: Literal[2] = 2
    trend: Trend = "UNDEFINED"
    major_high: float | None = None
    major_high_idx: int | None = None
    major_high_id: str | None = None
    major_low: float | None = None
    major_low_idx: int | None = None
    major_low_id: str | None = None
    protected_low: float | None = None
    protected_high: float | None = None
    last_event: StructureEvent | None = None
    trend_since_ms: int | None = None
    seen_pivots: tuple[str, ...] = ()


def no_sweep(timeframe: str, bar_index: int, lookback_bars: int, direction: str) -> None:
    """Dormant injected query; liquidity.py will replace this with real evidence."""
    return None


def evaluate_structure(
    state: StructureState,
    bars: Sequence[Bar],
    pivots: Sequence[Pivot],
    atr: float | None,
    config: StructureConfig,
    sweep_query: SweepQuery = no_sweep,
) -> StructureState:
    if not bars or not bars[-1].complete:
        return state
    bar = bars[-1]
    idx = len(bars) - 1
    changes: dict[str, object] = {}
    seen = list(state.seen_pivots)
    for pivot in pivots:
        if not pivot.confirmed or not pivot.significant or pivot.id in seen:
            continue
        if pivot.confirmed_at_idx is None or pivot.confirmed_at_idx > idx:
            raise ValueError("STRUCTURE_FUTURE_PIVOT")
        seen.append(pivot.id)
        high = pivot.side == "HIGH"
        if (high and state.trend == "BEARISH" and state.protected_high is not None) or (
            not high and state.trend == "BULLISH" and state.protected_low is not None
        ):
            continue
        side = "high" if high else "low"
        changes.update(
            {
                f"major_{side}": pivot.price,
                f"major_{side}_idx": pivot.idx,
                f"major_{side}_id": pivot.id,
            }
        )
    current = StructureState.model_validate(
        state.model_dump() | changes | {"seen_pivots": tuple(seen)}
    )
    if atr is None or atr <= 0:
        return current
    for direction, level, origin, swing_id in [
        ("UP", current.major_high, current.major_high_idx, current.major_high_id),
        ("DOWN", current.major_low, current.major_low_idx, current.major_low_id),
    ]:
        if level is None or origin is None or swing_id is None:
            continue
        distance = bar.c - level if direction == "UP" else level - bar.c
        if distance <= 0:
            continue
        if distance + 1e-12 < config.min_break_atr * atr:
            logger.debug(
                "structure near miss",
                extra={
                    "timeframe": bar.tf,
                    "bar_index": idx,
                    "distance": distance,
                    "required": config.min_break_atr * atr,
                },
            )
            continue
        after: Trend = "BULLISH" if direction == "UP" else "BEARISH"
        kind: Literal["BOS", "CHoCH"] = "BOS" if current.trend in ("UNDEFINED", after) else "CHoCH"
        sweep = (
            sweep_query(bar.tf, idx, config.mss_sweep_lookback_bars, direction) if kind == "CHoCH" else None
        )
        interval = range(origin, idx + 1)
        extreme = (
            min(interval, key=lambda i: bars[i].l)
            if direction == "UP"
            else max(interval, key=lambda i: bars[i].h)
        )
        protection = bars[extreme].l if direction == "UP" else bars[extreme].h
        at = bar.t_open_ms + timeframe_ms(bar.tf)
        source_indices = tuple(range(origin, idx + 1))
        source_ids = tuple(bars[i].id for i in source_indices)
        event = StructureEvent(
            id=content_hash(
                {
                    "tf": bar.tf,
                    "kind": kind,
                    "direction": direction,
                    "swing": swing_id,
                    "bar": bar.id,
                },
                bar.digits,
            ),
            kind=kind,
            is_mss=sweep is not None,
            direction="UP" if direction == "UP" else "DOWN",
            level=level,
            broken_swing_id=swing_id,
            broken_swing_idx=origin,
            break_bar_idx=idx,
            break_close=bar.c,
            timeframe=bar.tf,
            trend_before=current.trend,
            trend_after=after,
            atr_at_break=atr,
            t_ms=at,
            sweep_event_id=sweep,
            source_bars=source_indices,
            source_object_ids=source_ids,
        )
        protected_id = content_hash(
            {"event": event.id, "idx": extreme, "price": protection, "source": bars[extreme].id},
            bar.digits,
        )
        values: dict[str, object] = {
            "trend": after,
            "last_event": event,
            "protected_low": protection if direction == "UP" else None,
            "protected_high": protection if direction == "DOWN" else None,
            "trend_since_ms": at if current.trend != after else current.trend_since_ms,
        }
        if direction == "UP":
            values.update(
                major_high=None,
                major_high_idx=None,
                major_high_id=None,
                major_low=protection,
                major_low_idx=extreme,
                major_low_id=protected_id,
            )
        else:
            values.update(
                major_low=None,
                major_low_idx=None,
                major_low_id=None,
                major_high=protection,
                major_high_idx=extreme,
                major_high_id=protected_id,
            )
        return StructureState.model_validate(current.model_dump() | values)
    return current


@dataclass(frozen=True)
class StructureCursor:
    config: StructureConfig
    swings: SwingCursor
    state: StructureState
    events: tuple[StructureEvent, ...] = ()


def advance_structure(
    cursor: StructureCursor | None,
    bar: Bar,
    config: StructureConfig | None = None,
    *,
    swing_config: SwingConfig | None = None,
    sweep_query: SweepQuery = no_sweep,
    bar_phase: Literal["OPEN", "INTRA", "CLOSE"] = "CLOSE",
) -> StructureCursor | None:
    if bar_phase != "CLOSE" or not bar.complete:
        return cursor
    settings = cursor.config if cursor else config or StructureConfig()
    if cursor and config is not None and config != cursor.config:
        raise ValueError("structure parameters changed; regenerate")
    swings = advance_swings(cursor.swings if cursor else None, bar, swing_config)
    previous = cursor.state if cursor else StructureState()
    state = evaluate_structure(
        previous, swings.bars, swings.snapshot.major, swings.snapshot.atr[-1], settings, sweep_query
    )
    events = cursor.events if cursor else ()
    if state.last_event and state.last_event != previous.last_event:
        events = (*events, state.last_event)
    return StructureCursor(settings, swings, state, events)


def structure(
    bars: Sequence[Bar],
    config: StructureConfig | None = None,
    *,
    swing_config: SwingConfig | None = None,
    sweep_query: SweepQuery = no_sweep,
) -> StructureCursor | None:
    cursor = None
    for bar in bars:
        cursor = advance_structure(
            cursor, bar, config, swing_config=swing_config, sweep_query=sweep_query
        )
    return cursor
