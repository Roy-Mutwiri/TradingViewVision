"""Immutable creation records; lifecycle changes are separate immutable events."""

import hashlib
import json
from typing import Literal, Self

from pydantic import Field, model_validator

from oracle.data.analytical_days import trading_day
from oracle.models import Contract, Millis, NonNegative, Price, Text
from oracle.transport.errors import EngineError

CallState = Literal[
    "PENDING", "ACTIVE", "WIN", "LOSS", "SCRATCH", "NEVER_TRIGGERED", "VOID_DATA", "CANCELLED"
]
CancelReason = Literal[
    "SUPERSEDED_BY_NEW_ANALYSIS", "STRUCTURE_INVALIDATED_BEFORE_ENTRY",
    "EVENT_EMBARGO", "DATA_DEGRADED", "OPERATOR_CANCELLED",
]
CANCEL_REASONS = {
    "SUPERSEDED_BY_NEW_ANALYSIS", "STRUCTURE_INVALIDATED_BEFORE_ENTRY",
    "EVENT_EMBARGO", "DATA_DEGRADED", "OPERATOR_CANCELLED",
}


class Call(Contract):
    id: str = ""
    created_ms: Millis
    kind: Literal["SETUP", "STRUCTURE"]
    direction: Literal["LONG", "SHORT"]
    entry_lo: Price
    entry_hi: Price
    entry_ref: Price | None = None
    trigger_price: Price | None = None
    invalidation: Price
    target: Price
    expires_ms: Millis
    state_hash: Text
    reason: Text
    reason_chain: tuple[Text, ...] = ()
    symbol: Text
    clock_version: int = Field(ge=1, strict=True)
    state: CallState = "PENDING"
    resolved_ms: Millis | None = None
    mfe: NonNegative | None = None
    mae: NonNegative | None = None
    eval_from_ms: Millis = 0
    eval_to_ms: Millis = 0
    day_boundary: str = "17:00 America/New_York"
    created_trading_day: str = ""
    resolved_trading_day: str | None = None
    gap_skipped: bool = False
    timeframe: str | None = None
    tp2: Price | None = None
    in_ote: bool | None = None
    ob_id: str | None = None
    structure_event_id: str | None = None
    target_pool_id: str | None = None
    source_bars: tuple[int, ...] = ()
    grade: Literal["A", "B", "C"] = "A"
    grade_notes: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def validate_call(self) -> Self:
        if self.entry_lo > self.entry_hi or self.expires_ms <= self.created_ms:
            raise EngineError("CALL_GEOMETRY_INVALID", "Call requires ordered bounds and a future deadline")
        if self.kind == "STRUCTURE" and self.entry_lo != self.entry_hi:
            raise EngineError("CALL_GEOMETRY_INVALID", "Structure calls require a single trigger level")
        if self.direction == "LONG":
            valid = self.invalidation < self.entry_lo <= self.entry_hi < self.target
        else:
            valid = self.target < self.entry_lo <= self.entry_hi < self.invalidation
        if not valid:
            raise EngineError("CALL_GEOMETRY_INVALID", "Target and invalidation must bracket entry")
        if self.entry_ref is not None and not self.entry_lo <= self.entry_ref <= self.entry_hi:
            raise EngineError("CALL_ENTRY_TRIGGER_MISMATCH", "Entry reference must be inside the entry zone")
        if self.trigger_price is not None and self.trigger_price != self.entry_ref:
            raise EngineError(
                "CALL_ENTRY_TRIGGER_MISMATCH",
                "Recorded trigger price must equal the frozen entry reference",
            )
        terminal = self.state not in {"PENDING", "ACTIVE"}
        if terminal != (self.resolved_ms is not None):
            raise ValueError("Terminal snapshots require a resolution timestamp")
        if self.resolved_ms is not None and self.resolved_ms < self.created_ms:
            raise ValueError("Resolution cannot precede creation")
        derived = {
            "eval_from_ms": ((self.created_ms + 59999) // 60000) * 60000,
            "eval_to_ms": self.expires_ms // 60000 * 60000,
            "created_trading_day": trading_day(self.created_ms, self.day_boundary).isoformat(),
            "resolved_trading_day": trading_day(self.resolved_ms, self.day_boundary).isoformat()
            if self.resolved_ms is not None else None,
        }
        for name, value in derived.items():
            supplied = getattr(self, name)
            if supplied not in (0, "", None) and supplied != value:
                raise ValueError("Call audit boundaries do not match its timestamps")
            object.__setattr__(self, name, value)
        identity = self.model_dump(exclude={
            "id", "state", "resolved_ms", "resolved_trading_day", "mfe", "mae", "gap_skipped",
            "trigger_price",
        })
        if self.timeframe is None:
            for optional in ("timeframe", "tp2", "in_ote", "ob_id", "structure_event_id", "target_pool_id", "source_bars", "entry_ref"):
                identity.pop(optional)
        elif self.entry_ref is None:
            identity.pop("entry_ref")  # Existing produced ledgers remain readable.
        if not self.reason_chain:
            identity.pop("reason_chain")  # Existing ledger IDs remain valid.
        if self.grade == "A":
            identity.pop("grade")  # Grade A call goldens keep their historical IDs.
        if not self.grade_notes:
            identity.pop("grade_notes")
        # Preserve exact prices: two-decimal rounding must not merge distinct calls.
        digest = hashlib.blake2b(json.dumps(
            identity, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode(), digest_size=8).hexdigest()
        if self.id and self.id != digest:
            raise ValueError("Call ID does not match its immutable terms")
        object.__setattr__(self, "id", digest)
        return self

    @property
    def entry_mid(self) -> float:
        return (self.entry_lo + self.entry_hi) / 2

    @property
    def effective_entry_ref(self) -> float:
        """Compatibility fallback for ledgers created before entry_ref was frozen."""
        return self.entry_ref if self.entry_ref is not None else self.entry_mid

    @property
    def risk(self) -> float:
        return abs(self.effective_entry_ref - self.invalidation)

    @property
    def reward_r(self) -> float:
        return abs(self.target - self.effective_entry_ref) / self.risk


class CallEvent(Contract):
    sequence: int = Field(ge=0)
    call_id: Text
    action: Literal["CREATE", "ADVANCE", "CANCEL", "AMBIGUOUS"]
    at_ms: Millis
    call: Call
    reason: Text
    ambiguous: bool = False
    covered_until_ms: Millis
    prior_bid_close: Price | None = None


class CallRow(Contract):
    call: Call
    cancelled: bool = False
    cancellation_reason: str | None = None
    resolution_reason: str | None = None
    ambiguous: bool = False
    prior_bid_close: Price | None = None


class CallStats(Contract):
    produced: int = 0
    triggered: int = 0
    wins: int = 0
    losses: int = 0
    scratch: int = 0
    never_triggered: int = 0
    void_data: int = 0
    cancelled: int = 0
    pending: int = 0
    active: int = 0
    ambiguous: int = 0
    gap_skipped: int = 0
    resolved: int = 0
    hit_rate: float | None = None
    expectancy: float | None = None


class CallBoard(Contract):
    rows: list[CallRow] = []
    today: CallStats = CallStats()
    last_20: CallStats = CallStats()
    all_time: CallStats = CallStats()
    today_label: str = "TODAY Â· from 17:00 NY"
    today_trading_day: str = ""

