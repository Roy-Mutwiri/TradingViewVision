"""Frozen OB geometry, distinct from a three-candle FVG."""

import hashlib
import json
import math
from typing import Literal, Self

from pydantic import model_validator

from oracle.models import Contract, Timeframe


class OBGeometry(Contract):
    schema_version: Literal[1] = 1
    symbol: str = "XAUUSD"
    tf: Timeframe
    direction: Literal["BULLISH", "BEARISH"]
    price_lo: float
    price_hi: float
    ce: float
    size: float
    atr_at_creation: float
    created_ms: int
    t_start_ms: int
    created_idx: int
    origin_idx: int
    leg_start_idx: int
    boundary: Literal["body_to_wick", "full_range", "body_only"]
    displacement_atr: float
    source_bars: tuple[int, ...]
    source_object_ids: tuple[str, ...]
    fvg_ids: tuple[str, ...]
    constituent_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid(self) -> Self:
        if not all(
            math.isfinite(v)
            for v in (
                self.price_lo,
                self.price_hi,
                self.ce,
                self.size,
                self.atr_at_creation,
                self.displacement_atr,
            )
        ):
            raise ValueError("OB requires finite prices and frozen ATR")
        if (
            self.price_hi <= self.price_lo
            or self.atr_at_creation <= 0
            or self.size != self.price_hi - self.price_lo
            or self.ce != (self.price_hi + self.price_lo) / 2
        ):
            raise ValueError("OB bounds, midpoint or ATR invalid")
        if len(self.source_bars) != len(self.source_object_ids):
            raise ValueError("OB source indices and IDs must match")
        return self

    @property
    def id(self) -> str:
        payload = (
            json.dumps(self.constituent_ids, separators=(",", ":"))
            if self.constituent_ids
            else self.canonical_json()
        )
        return hashlib.blake2b(payload.encode(), digest_size=8).hexdigest()


class OBRecord(Contract):
    geometry: OBGeometry
    state: Literal["FRESH", "TOUCHED", "MITIGATED", "BREAKER", "INVALID", "MERGED"] = "FRESH"
    validated_by_event_id: str
    validation_event_ids: tuple[str, ...] = ()
    validation_kind: Literal["BOS", "CHoCH"]
    parent_id: str | None = None
    inversion_depth: int = 0
    mitigated_ms: int | None = None
    mitigated_bar_open_ms: int | None = None
    last_seq: int = -1

    @property
    def id(self) -> str:
        return self.geometry.id


class OBCandidate(Contract):
    id: str
    geometry: OBGeometry
    born_bar_index: int
    state: Literal["CANDIDATE", "PROMOTED", "DISCARDED"] = "CANDIDATE"
    reason: str | None = None
    criterion: str | None = None
    decision_id: str = "pending"
    fidelity: Literal["TICK", "M1", "BAR"]
