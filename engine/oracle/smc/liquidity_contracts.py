"""Frozen pool geometry and distinct, unscoreable pending sweep evidence."""

from typing import Literal

from oracle.models import Contract, Timeframe


class LiquidityGeometry(Contract):
    schema_version: Literal[1] = 1
    tf: Timeframe
    direction: Literal["BULLISH", "BEARISH"]
    side: Literal["HIGH", "LOW"]
    name: str
    level: float
    price_lo: float
    price_hi: float
    ce: float
    size: Literal[0] = 0
    atr_at_creation: float
    created_ms: int
    t_start_ms: int
    source_bars: tuple[int, ...]
    source_object_ids: tuple[str, ...]


class Pool(Contract):
    id: str
    geometry: LiquidityGeometry
    strength: int
    state: Literal["FRESH", "TOUCHED", "SWEPT", "BROKEN"] = "FRESH"
    touch_bars: tuple[int, ...] = ()
    touch_times: tuple[int, ...] = ()
    named: bool = False
    scope_key: str | None = None
    swept_ms: int | None = None
    sweep_event_id: str | None = None

    @property
    def level(self) -> float:
        return self.geometry.level


class SweepCandidate(Contract):
    id: str
    pool_id: str
    geometry: LiquidityGeometry
    state: Literal["CANDIDATE", "PROMOTED", "DISCARDED"] = "CANDIDATE"
    born_bar_idx: int
    born_seq: int
    penetration_atr: float
    threshold_at_creation: float
    extreme: float
    fidelity: Literal["TICK", "M1", "BAR"]
    reason: str | None = None
    decision_id: str


class Sweep(Contract):
    id: str
    pool_id: str
    timeframe: Timeframe
    side: Literal["HIGH", "LOW"]
    level: float
    extreme: float
    penetration_bar_idx: int
    confirmed_bar_idx: int
    reclaim_bar_idx: int
    confirmed_ms: int
    reclaim_ms: int
    atr_at_creation: float
    fidelity: Literal["TICK", "M1", "BAR"]
    source_bars: tuple[int, ...]
    source_object_ids: tuple[str, ...]
