"""Resolve complete BID M1 intervals within the call's frozen life."""

from collections.abc import Callable
from typing import Literal

from pydantic import model_validator

from oracle.analysis.contracts import Call
from oracle.analysis.ledger import CallLedger
from oracle.analysis.scoring import TERMINAL
from oracle.models import Bar, Contract, Millis, Text


class QualityWindow(Contract):
    start_ms: Millis
    end_ms: Millis
    state: Literal["STALE", "GAPPED"]
    reason: Text

    @model_validator(mode="after")
    def bounds(self) -> "QualityWindow":
        if self.end_ms <= self.start_ms:
            raise ValueError("Quality window must have positive duration")
        return self


class CallResolver:
    def __init__(self, ledger: CallLedger, tick_size: float) -> None:
        if tick_size <= 0 or not tick_size < float("inf"):
            raise ValueError("Positive finite tick size required")
        self.ledger = ledger
        self.epsilon = tick_size / 2

    def evaluate(
        self,
        call_id: str,
        bars: list[Bar],
        now_ms: int,
        *,
        clock_version: int,
        quality: list[QualityWindow] | None = None,
        is_tradeable: Callable[[int], bool] | None = None,
        coverage_through_ms: int | None = None,
        can_activate: Callable[[Call], bool] | None = None,
    ) -> Call:
        with self.ledger.lock:
            row = self.ledger.row(call_id)
            call = row.call
            if row.cancelled or call.state in TERMINAL:
                return call
            if any(bar.tf != "M1" or bar.symbol != call.symbol for bar in bars):
                raise ValueError("Resolver accepts only same-symbol BID M1 bars")
            if clock_version != call.clock_version:
                raise ValueError("Clock version differs from the call's frozen provenance")
            start = call.eval_from_ms
            deadline = call.eval_to_ms
            cursor = max(start, self.ledger.covered_until(call_id))
            horizon = (
                min(now_ms, coverage_through_ms) if coverage_through_ms is not None else now_ms
            )
            limit = min(deadline, horizon // 60000 * 60000)
            eligible: dict[int, Bar] = {}
            for candidate in bars:
                if not candidate.complete or not cursor <= candidate.t_open_ms < limit:
                    continue
                if candidate.t_open_ms % 60000:
                    raise ValueError("BID M1 bars must open on minute boundaries")
                previous = eligible.get(candidate.t_open_ms)
                if previous and (previous.o, previous.h, previous.l, previous.c) != (
                    candidate.o,
                    candidate.h,
                    candidate.l,
                    candidate.c,
                ):
                    raise ValueError("Conflicting M1 coverage; reconcile source before resolution")
                eligible[candidate.t_open_ms] = candidate
            for t in range(cursor, limit, 60000):
                end = t + 60000
                failure = next(
                    (q for q in quality or [] if q.start_ms < end and q.end_ms > t), None
                )
                bar = eligible.get(t)
                if (
                    bar is None
                    and is_tradeable
                    and not is_tradeable(t)
                    and not is_tradeable(end - 1)
                ):
                    call = self.ledger.advance(
                        call_id,
                        call.state,
                        end,
                        end,
                        "Verified session closure; no BID entry trades",
                        mfe=call.mfe,
                        mae=call.mae,
                    )
                    continue
                if failure or bar is None:
                    reason = (
                        f"{failure.state}: {failure.reason}; [{failure.start_ms}, {failure.end_ms})"
                        if failure
                        else f"GAPPED: missing BID M1 coverage [{t}, {end})"
                    )
                    return self.ledger.advance(
                        call_id, "VOID_DATA", end, t, reason, mfe=call.mfe, mae=call.mae
                    )
                target = (
                    bar.h >= call.target - self.epsilon
                    if call.direction == "LONG"
                    else bar.l <= call.target + self.epsilon
                )
                invalid = (
                    bar.l <= call.invalidation + self.epsilon
                    if call.direction == "LONG"
                    else bar.h >= call.invalidation - self.epsilon
                )
                entering = (
                    call.state == "PENDING"
                    and bar.h >= call.entry_lo - self.epsilon
                    and bar.l <= call.entry_hi + self.epsilon
                )
                if entering and can_activate is not None and not can_activate(call):
                    entering = False
                previous_close = self.ledger.row(call_id).prior_bid_close
                gap_skipped = bool(
                    call.state == "PENDING"
                    and previous_close is not None
                    and (
                        (
                            previous_close < call.entry_lo - self.epsilon
                            and bar.l > call.entry_hi + self.epsilon
                        )
                        or (
                            previous_close > call.entry_hi + self.epsilon
                            and bar.h < call.entry_lo - self.epsilon
                        )
                    )
                )
                state = "ACTIVE" if entering else call.state
                trigger_price = (
                    call.effective_entry_ref
                    if entering and call.entry_ref is not None
                    else call.trigger_price
                )
                if entering and call.timeframe is not None and call.entry_ref is None:
                    raise ValueError("Produced call is missing its frozen entry reference")
                if entering and call.entry_ref is not None and trigger_price != call.entry_ref:
                    raise ValueError("Entry reference differs from recorded trigger price")
                mfe, mae = call.mfe, call.mae
                if state == "ACTIVE":
                    favourable = (
                        (bar.h - call.effective_entry_ref)
                        if call.direction == "LONG"
                        else (call.effective_entry_ref - bar.l)
                    ) / call.risk
                    adverse = (
                        (call.effective_entry_ref - bar.l)
                        if call.direction == "LONG"
                        else (bar.h - call.effective_entry_ref)
                    ) / call.risk
                    mfe = max(mfe or 0, favourable, 0)
                    mae = max(mae or 0, adverse, 0)
                    if invalid or target:
                        return self.ledger.advance(
                            call_id,
                            "LOSS" if invalid else "WIN",
                            end,
                            end,
                            "Both BID M1 wicks touched target and invalidation; scored against call"
                            if invalid and target
                            else "BID M1 invalidation wick touched"
                            if invalid
                            else "BID M1 target wick touched",
                            mfe=mfe,
                            mae=mae,
                            ambiguous=invalid and target,
                            gap_skipped=gap_skipped,
                            prior_bid_close=bar.c,
                            trigger_price=trigger_price,
                        )
                call = self.ledger.advance(
                    call_id,
                    state,
                    end,
                    end,
                    "BID gap skipped entry zone"
                    if gap_skipped
                    else "Closed BID M1 coverage evaluated",
                    mfe=mfe,
                    mae=mae,
                    gap_skipped=gap_skipped,
                    prior_bid_close=bar.c,
                    trigger_price=trigger_price,
                )
            if now_ms >= call.expires_ms and limit >= deadline:
                return self.ledger.advance(
                    call_id,
                    "SCRATCH" if call.state == "ACTIVE" else "NEVER_TRIGGERED",
                    call.expires_ms,
                    limit,
                    "Deadline reached with covered BID M1 data",
                    mfe=call.mfe,
                    mae=call.mae,
                )
            return call
