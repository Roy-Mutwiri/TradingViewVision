"""Append-only call ledger; the initial terms are never replaced on disk."""

import os
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from oracle.analysis.contracts import (
    CANCEL_REASONS,
    Call,
    CallEvent,
    CallRow,
    CallState,
    CancelReason,
)
from oracle.analysis.scoring import TERMINAL
from oracle.transport.errors import EngineError


class CallLedger:
    def __init__(self, path: Path | None = None, min_call_life_ms: int = 300000) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.min_call_life_ms = min_call_life_ms
        self.events: list[CallEvent] = []
        self._rows: dict[str, CallRow] = {}
        self._covered: dict[str, int] = {}
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    event = CallEvent.model_validate_json(line)
                    self._validate(event)
                    self._apply(event)

    @property
    def rows(self) -> list[CallRow]:
        with self.lock:
            return list(self._rows.values())

    def row(self, call_id: str) -> CallRow:
        with self.lock:
            return self._rows[call_id]

    def covered_until(self, call_id: str) -> int:
        with self.lock:
            return self._covered[call_id]

    def _validate(self, event: CallEvent) -> None:
        if event.sequence != len(self.events) or event.call_id != event.call.id:
            raise ValueError("Invalid call ledger sequence or identity")
        previous = self._rows.get(event.call_id)
        if event.action == "CREATE":
            if previous or event.call.state != "PENDING" or event.call.resolved_ms is not None:
                raise ValueError("Creation must be a new pending call")
            if event.call.mfe is not None or event.call.mae is not None:
                raise ValueError("Creation cannot contain retrospective excursions")
            if event.at_ms != event.call.created_ms:
                raise ValueError("Creation timestamp must match call")
            return
        if previous is None or previous.cancelled or previous.call.state in TERMINAL:
            raise ValueError("Terminal or cancelled call cannot advance")
        immutable = {
            "state", "resolved_ms", "resolved_trading_day", "mfe", "mae", "gap_skipped",
            "trigger_price",
        }
        if previous.call.model_dump(exclude=immutable) != event.call.model_dump(exclude=immutable):
            raise ValueError("Call terms cannot be edited")
        if event.at_ms < previous.call.created_ms:
            raise ValueError("Lifecycle event precedes creation")
        if event.covered_until_ms < self._covered[event.call_id]:
            raise ValueError("Coverage cannot move backwards")
        if event.action == "CANCEL":
            if previous.call.state != "PENDING":
                raise EngineError("CALL_ACTIVE_CANNOT_CANCEL", "Only pending calls may be cancelled")
            if event.call.state != "CANCELLED" or event.reason not in CANCEL_REASONS:
                raise ValueError("Cancellation requires a terminal state and a closed reason")
        elif event.call.state == "CANCELLED":
            raise ValueError("Cancellation must use a CANCEL event")
        if event.call.state == "VOID_DATA" and not event.reason.startswith(("STALE:", "GAPPED:")):
            raise ValueError("VOID_DATA requires an explicit data-quality reason")
        if previous.call.state == "ACTIVE" and event.call.state in {"PENDING", "NEVER_TRIGGERED"}:
            raise ValueError("Active calls cannot return to pending")
        if event.call.state in TERMINAL and event.call.resolved_ms != event.at_ms:
            raise ValueError("Resolution needs its event timestamp")
        if event.ambiguous and event.call.state != "LOSS":
            raise ValueError("Ambiguous resolution must be a loss")

    def _apply(self, event: CallEvent) -> None:
        previous = self._rows.get(event.call_id)
        self._rows[event.call_id] = CallRow(
            call=event.call,
            cancelled=event.action == "CANCEL",
            cancellation_reason=event.reason if event.action == "CANCEL" else None,
            resolution_reason=event.reason if event.call.state in TERMINAL else None,
            ambiguous=event.ambiguous or bool(previous and previous.ambiguous),
            prior_bid_close=event.prior_bid_close,
        )
        self._covered[event.call_id] = event.covered_until_ms
        self.events.append(event)

    def _append(self, event: CallEvent) -> None:
        self._validate(event)
        if self.path:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(event.canonical_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        self._apply(event)

    def create(self, call: Call) -> Call:
        with self.lock:
            call = Call.model_validate(call.model_dump())
            if call.state != "PENDING" or call.mfe is not None or call.mae is not None or call.gap_skipped:
                raise EngineError("CALL_CREATION_STATE_INVALID", "New calls must be pending and unevaluated")
            if call.timeframe is not None and call.entry_ref is None:
                raise EngineError(
                    "CALL_ENTRY_TRIGGER_MISMATCH",
                    "Produced calls must freeze the exact trigger price at construction",
                )
            if call.expires_ms <= call.created_ms + self.min_call_life_ms:
                raise EngineError("CALL_LIFE_TOO_SHORT", "Call deadline must exceed minimum life",
                                  {"min_call_life_ms": self.min_call_life_ms})
            if call.id in self._rows:
                return self._rows[call.id].call
            self._append(CallEvent(sequence=len(self.events), call_id=call.id, action="CREATE",
                                   at_ms=call.created_ms, call=call, reason=call.reason,
                                   covered_until_ms=call.created_ms))
            return call

    def submit(self, terms: dict[str, Any]) -> Call:
        """Validate producer input before anything reaches the append-only log."""
        try:
            call = Call.model_validate(terms)
        except ValidationError as exc:
            raise EngineError("CALL_NOT_FALSIFIABLE", "Call requires valid target, invalidation and deadline") from exc
        return self.create(call)

    def cancel(self, call_id: str, reason: CancelReason, *, at_ms: int | None = None) -> None:
        with self.lock:
            call = self._rows[call_id].call
            if call.state != "PENDING":
                raise EngineError("CALL_ACTIVE_CANNOT_CANCEL", "Only pending calls may be cancelled")
            if reason not in CANCEL_REASONS:
                raise EngineError("CALL_CANCEL_REASON_INVALID", "Choose a defined cancellation reason")
            stamp = at_ms if at_ms is not None else time.time_ns() // 1000000
            cancelled = Call.model_validate(call.model_dump() | {
                "state": "CANCELLED", "resolved_ms": stamp,
            })
            self._append(CallEvent(sequence=len(self.events), call_id=call_id, action="CANCEL",
                                   at_ms=stamp, call=cancelled, reason=reason,
                                   covered_until_ms=self._covered[call_id],
                                   prior_bid_close=self._rows[call_id].prior_bid_close))

    def advance(self, call_id: str, state: CallState, at_ms: int, covered_until_ms: int,
                reason: str, mfe: float | None = None, mae: float | None = None,
                ambiguous: bool = False, gap_skipped: bool = False,
                prior_bid_close: float | None = None,
                trigger_price: float | None = None) -> Call:
        with self.lock:
            current = self._rows[call_id].call
            updated = Call.model_validate(current.model_dump() | {
                "state": state, "resolved_ms": at_ms if state in TERMINAL else None,
                "mfe": mfe, "mae": mae,
                "gap_skipped": current.gap_skipped or gap_skipped,
                "trigger_price": current.trigger_price or trigger_price,
            })
            self._append(CallEvent(
                sequence=len(self.events), call_id=call_id,
                action="AMBIGUOUS" if ambiguous else "ADVANCE", at_ms=at_ms,
                call=updated, reason=reason, ambiguous=ambiguous,
                covered_until_ms=covered_until_ms,
                prior_bid_close=prior_bid_close or self._rows[call_id].prior_bid_close,
            ))
            return updated
