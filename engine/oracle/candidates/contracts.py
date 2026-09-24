import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field

from oracle.models import Contract, Millis, Price, Timeframe
from oracle.smc.imbalance import FVGGeometry
from oracle.smc.liquidity_contracts import LiquidityGeometry
from oracle.smc.ob_contracts import OBGeometry

Fidelity = Literal["TICK", "M1", "BAR"]
CANDIDATE_SCHEMA_VERSION = 2
DiscardReason = Literal[
    "INVALIDATED", "SUPERSEDED", "MERGED", "FAILED_CRITERIA", "STALE", "DATA_GAP"
]


class EvalPoint(Contract):
    seq: Annotated[int, Field(ge=0)]
    t_broker_ms: Millis
    price: Price
    bar_index: Annotated[int, Field(ge=0)]
    bar_phase: Literal["OPEN", "INTRA", "CLOSE"]
    source: Literal["LIVE_TICK", "M1_SYNTH", "BAR_COARSE", "RECORDED"]
    fidelity: Fidelity


class Measurement(Contract):
    price_a: Price
    price_b: Price
    value: float
    unit: Literal["pts", "ATR", "R"]
    criterion: str
    threshold: float
    passed: bool


class Decision(Contract):
    seq: Annotated[int, Field(ge=0)]
    t_broker_ms: Millis
    object_id: str
    kind: Literal["FVG", "OB", "POOL", "SWEEP"]
    action: Literal["CREATE", "UPDATE", "PROMOTE", "DISCARD"]
    reason: DiscardReason | None = None
    fidelity: Fidelity
    tf: Timeframe
    t_utc_ms: Millis
    criterion: str | None = None
    confirmed_id: str | None = None
    union_id: str | None = None
    measurement: Measurement | None = None
    geometry: FVGGeometry | OBGeometry | LiquidityGeometry
    source_bars: tuple[int, ...]
    source_object_ids: tuple[str, ...]

    @property
    def id(self) -> str:
        return hashlib.blake2b(self.canonical_json().encode(), digest_size=8).hexdigest()


class CandidateObject(Contract):
    id: str
    kind: Literal["FVG"] = "FVG"
    state: Literal["CANDIDATE", "PROMOTED", "DISCARDED"] = "CANDIDATE"
    geometry: FVGGeometry
    born_seq: int
    born_bar_index: int
    fidelity: Fidelity
    reason: DiscardReason | None = None
    criterion: str | None = None
    decision_id: str


def decisions_hash(decisions: list[Decision]) -> str:
    lines = [
        json.dumps((d.seq, d.object_id, d.action, d.reason), separators=(",", ":"))
        for d in decisions
    ]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()
