"""Deterministic construction of falsifiable calls from confirmed SMC evidence."""

from collections import Counter
from typing import Literal

from oracle.analysis.contracts import Call
from oracle.config import CallsConfig, TradeConfig
from oracle.models import Bar, Contract, content_hash, timeframe_ms
from oracle.smc.imbalance import FVGRecord
from oracle.smc.liquidity import LiquidityEngine
from oracle.smc.ob_contracts import OBRecord
from oracle.smc.structure import StructureState

Reject = Literal[
    "TREND_UNDEFINED",
    "DIRECTION_MISMATCH",
    "WRONG_RANGE_HALF",
    "NO_TARGET_IN_RANGE",
    "STOP_TOO_WIDE",
    "STOP_TOO_TIGHT",
    "R_BELOW_MIN",
    "TARGET_BEYOND_MAX_R",
    "ENTRY_TOO_FAR",
    "PENDING_TOTAL",
    "CONCURRENT_TOTAL",
    "CONCURRENT_SAME_TF",
    "OPPOSING_HTF_CALL",
    "CORRELATED_ZONE",
    "ZONE_SPENT",
    "NO_STRUCTURE_EVENT",
    "ZONE_OUTSIDE_RANGE",
]



class DryRunGate(Contract):
    code: str
    passed: bool
    threshold: float | None = None
    value: float | None = None
    note: str | None = None


class CallDryRun(Contract):
    tf: str
    direction: Literal["LONG", "SHORT"]
    grade: Literal["A", "B", "C"] = "A"
    grade_notes: tuple[str, ...] = ()
    zone_id: str
    zone_lo: float
    zone_hi: float
    entry_ref: float
    stop: float | None = None
    tp1: float | None = None
    tp1_name: str | None = None
    tp1_pool_id: str | None = None
    reward_r: float | None = None
    min_r: float
    first_fail: str | None = None
    passes: bool = False
    gates: tuple[DryRunGate, ...] = ()
    distance_to_zone: float = 0.0
    target_close_note: str | None = None
class CallProducer:
    def __init__(self, trade: TradeConfig, calls: CallsConfig) -> None:
        self.trade, self.calls = trade, calls
        self.rejections: Counter[str] = Counter()
        self.rejections_by_tf: Counter[tuple[str, str]] = Counter()
        self.used_zones: set[str] = set()
        self.spent_zones: set[str] = set()
        self.spent_logged: set[str] = set()

    def reject(self, reason: Reject, tf: str) -> None:
        self.rejections[reason] += 1
        self.rejections_by_tf[(tf, reason)] += 1

    def htf_arbitration(
        self, active: list[Call], direction: Literal["LONG", "SHORT"], tf: str
    ) -> tuple[list[Call], list[str]]:
        """Published calls remain accountable; later setups are suppressed by construct()."""
        return active, []

    def dry_run(
        self,
        *,
        ob: OBRecord,
        fvgs: list[FVGRecord],
        structure: StructureState,
        liquidity: LiquidityEngine,
        bar: Bar,
        atr: float,
        active: list[Call],
    ) -> CallDryRun:
        """Read-only call construction audit. No counters, ledger writes or zone reservations."""
        g = ob.geometry
        direction: Literal["LONG", "SHORT"] = "LONG" if g.direction == "BULLISH" else "SHORT"
        lo, hi = g.price_lo, g.price_hi
        usable = []
        for f in [f for f in fvgs if f.eligible_for_a_setup and f.geometry.direction == g.direction]:
            a, b = max(lo, f.geometry.price_lo), min(hi, f.geometry.price_hi)
            if b > a and b - a >= self.trade.min_entry_zone_atr * atr:
                usable.append((a, b, f))
        if usable:
            lo, hi, _ = max(usable, key=lambda x: (x[1] - x[0], x[2].id))
        entry = hi if direction == "LONG" else lo
        distance = 0.0 if lo <= bar.c <= hi else min(abs(bar.c - lo), abs(bar.c - hi))
        gates: list[DryRunGate] = []

        def add(
            code: str,
            passed: bool,
            threshold: float | None = None,
            value: float | None = None,
            note: str | None = None,
        ) -> None:
            gates.append(
                DryRunGate(
                    code=code, passed=passed, threshold=threshold, value=value, note=note
                )
            )

        grade: Literal["A", "B", "C"] = "A"
        notes: list[str] = []
        stop: float | None = None
        target: float | None = None
        target_name: str | None = None
        target_pool_id: str | None = None
        reward_r: float | None = None
        close_note: str | None = None

        def done() -> CallDryRun:
            first = next((gate.code for gate in gates if not gate.passed), None)
            return CallDryRun(
                tf=g.tf,
                direction=direction,
                grade=grade,
                grade_notes=tuple(notes),
                zone_id=ob.id,
                zone_lo=lo,
                zone_hi=hi,
                entry_ref=entry,
                stop=stop,
                tp1=target,
                tp1_name=target_name,
                tp1_pool_id=target_pool_id,
                reward_r=reward_r,
                min_r=self.trade.min_r,
                first_fail=first,
                passes=first is None,
                gates=tuple(gates),
                distance_to_zone=distance,
                target_close_note=close_note,
            )

        add("ZONE_AVAILABLE", ob.id not in self.used_zones and ob.id not in self.spent_zones)
        add("TREND_DEFINED", structure.trend != "UNDEFINED")
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        add("DIRECTION_MATCH", structure.trend == expected)
        event = structure.last_event
        event_ok = event is not None and event.id in set(
            ob.validation_event_ids or (ob.validated_by_event_id,)
        )
        add("STRUCTURE_EVENT", event_ok)
        low, high = (
            (structure.protected_low, structure.major_high)
            if structure.trend == "BULLISH"
            else (structure.major_low, structure.protected_high)
        )
        if low is None or high is None or high <= low:
            add("DEALING_RANGE", False)
            return done()
        add("DEALING_RANGE", True)
        eq = (low + high) / 2
        inside_range = not (
            (direction == "SHORT" and (lo < eq or hi > high))
            or (direction == "LONG" and (lo < low or hi > eq))
        )
        add("ZONE_INSIDE_RANGE", inside_range or not self.calls.require_zone_inside_range, eq, entry)
        wrong_half = (direction == "LONG" and entry >= eq) or (
            direction == "SHORT" and entry <= eq
        )
        touched = bar.h >= lo and bar.l <= hi
        if wrong_half:
            if self.calls.grade_b.enabled and touched:
                grade = "B"
                notes.append("in premium" if direction == "LONG" else "in discount")
                add("RANGE_HALF", True, eq, entry, "trading as Grade B")
            else:
                add("WRONG_RANGE_HALF", False, eq, entry)
        else:
            add("RANGE_HALF", True, eq, entry)
        add(
            "ENTRY_DISTANCE",
            abs(entry - bar.c) <= self.trade.max_entry_distance_atr * atr,
            entry,
            abs(entry - bar.c),
        )
        stop = lo - self.trade.stop_buffer_atr * atr if direction == "LONG" else hi + self.trade.stop_buffer_atr * atr
        sweep = next(
            (s for s in reversed(liquidity.sweeps) if event is not None and s.id == event.sweep_event_id),
            None,
        )
        if sweep:
            stop = min(stop, sweep.extreme) if direction == "LONG" else max(stop, sweep.extreme)
            if grade == "B":
                notes.append(f"after {'sell-side' if sweep.side == 'LOW' else 'buy-side'} sweep")
        risk = abs(entry - stop)
        add("STOP_MIN", risk >= self.trade.min_stop_points, self.trade.min_stop_points, risk)
        add("STOP_CAP", risk <= self.trade.max_stop_atr * atr, self.trade.max_stop_atr * atr, risk)
        pools = liquidity.pools_above(entry, g.tf) if direction == "LONG" else liquidity.pools_below(entry, g.tf)
        pools = [
            p
            for p in pools
            if self.trade.min_tp_distance_atr * atr
            <= abs(p.level - entry)
            <= self.trade.max_tp_search_atr * atr
        ]
        add("TARGET_FOUND", bool(pools))
        if not pools:
            return done()
        pool = pools[0]
        eq_distance = abs(eq - entry)
        eq_ok = (
            (direction == "LONG" and eq > entry)
            or (direction == "SHORT" and eq < entry)
        ) and eq_distance >= self.trade.min_tp_distance_atr * atr
        if eq_ok and eq_distance <= abs(pool.level - entry):
            target, target_name = eq, "EQ"
        else:
            target, target_name, target_pool_id = pool.level, pool.geometry.name, pool.id
        if abs(target - bar.c) < self.trade.min_tp_distance_atr * atr:
            close_note = "target close to price  may sweep before pullback"
        reward_r = abs(target - entry) / max(0.000001, risk)
        add("R_MIN", reward_r >= self.trade.min_r, self.trade.min_r, reward_r)
        add("TARGET_MAX_R", reward_r <= self.trade.max_tp_r, self.trade.max_tp_r, reward_r)
        active_calls = [call for call in active if call.state == "ACTIVE"]
        pending_calls = [call for call in active if call.state == "PENDING"]
        add("PENDING_TOTAL", len(pending_calls) < self.calls.max_pending, self.calls.max_pending, len(pending_calls))
        add("CONCURRENT_TOTAL", len(active_calls) < self.calls.max_concurrent, self.calls.max_concurrent, len(active_calls))
        add("CONCURRENT_SAME_TF", not any(call.direction == direction and call.timeframe == g.tf for call in active_calls))
        add(
            "CORRELATED_ZONE",
            not any(
                call.direction == direction
                and max(call.entry_lo, lo) <= min(call.entry_hi, hi) + 0.5 * atr
                for call in active_calls
            ),
        )
        add("OPPOSING_HTF_CALL", not any(call.direction != direction for call in active_calls))
        return done()

    def construct(
        self,
        *,
        ob: OBRecord,
        fvgs: list[FVGRecord],
        structure: StructureState,
        liquidity: LiquidityEngine,
        bar: Bar,
        atr: float,
        clock_version: int,
        active: list[Call],
    ) -> Call | None:
        g = ob.geometry
        if ob.id in self.used_zones:
            return None
        if ob.id in self.spent_zones:
            if ob.id not in self.spent_logged:
                self.reject("ZONE_SPENT", g.tf)
                self.spent_logged.add(ob.id)
            return None
        if structure.trend == "UNDEFINED":
            self.reject("TREND_UNDEFINED", g.tf)
            return None
        direction: Literal["LONG", "SHORT"] = (
            "LONG" if ob.geometry.direction == "BULLISH" else "SHORT"
        )
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        if structure.trend != expected:
            self.reject("DIRECTION_MISMATCH", g.tf)
            return None
        event = structure.last_event
        if event is None or event.id not in set(
            ob.validation_event_ids or (ob.validated_by_event_id,)
        ):
            self.reject("NO_STRUCTURE_EVENT", g.tf)
            return None
        lo, hi = g.price_lo, g.price_hi
        eligible = [
            f for f in fvgs if f.eligible_for_a_setup and f.geometry.direction == g.direction
        ]
        intersections = [
            (max(lo, f.geometry.price_lo), min(hi, f.geometry.price_hi), f) for f in eligible
        ]
        usable = [
            x
            for x in intersections
            if x[1] > x[0] and x[1] - x[0] >= self.trade.min_entry_zone_atr * atr
        ]
        if usable:
            lo, hi, _ = max(usable, key=lambda x: (x[1] - x[0], x[2].id))
        # zone_touch freezes the first tradeable boundary as the entry reference.
        entry = hi if direction == "LONG" else lo
        if structure.trend == "BULLISH":
            low, high = structure.protected_low, structure.major_high
        else:
            low, high = structure.major_low, structure.protected_high
        if low is None or high is None or high <= low:
            self.reject("TREND_UNDEFINED", g.tf)
            return None
        eq = (low + high) / 2
        if (
            self.calls.require_zone_inside_range
            and (
                (direction == "SHORT" and (lo < eq or hi > high))
                or (direction == "LONG" and (lo < low or hi > eq))
            )
        ):
            self.reject("ZONE_OUTSIDE_RANGE", g.tf)
            return None
        wrong_range_half = (direction == "LONG" and entry >= eq) or (direction == "SHORT" and entry <= eq)
        zone_touched = bar.h >= lo and bar.l <= hi
        grade: Literal["A", "B", "C"] = "A"
        grade_notes: list[str] = []
        if wrong_range_half:
            if not self.calls.grade_b.enabled or not zone_touched:
                self.reject("WRONG_RANGE_HALF", g.tf)
                return None
            grade = "B"
            grade_notes.append("in premium" if direction == "LONG" else "in discount")
        if abs(entry - bar.c) > self.trade.max_entry_distance_atr * atr:
            self.reject("ENTRY_TOO_FAR", g.tf)
            return None
        stop = (
            lo - self.trade.stop_buffer_atr * atr
            if direction == "LONG"
            else hi + self.trade.stop_buffer_atr * atr
        )
        sweep = next((s for s in reversed(liquidity.sweeps) if s.id == event.sweep_event_id), None)
        if sweep:
            stop = min(stop, sweep.extreme) if direction == "LONG" else max(stop, sweep.extreme)
            if grade == "B":
                side_note = "sell-side" if sweep.side == "LOW" else "buy-side"
                grade_notes.append(f"after {side_note} sweep")
        risk = abs(entry - stop)
        if risk < self.trade.min_stop_points:
            self.reject("STOP_TOO_TIGHT", g.tf)
            return None
        if risk > self.trade.max_stop_atr * atr:
            self.reject("STOP_TOO_WIDE", g.tf)
            return None
        pools = (
            liquidity.pools_above(entry, g.tf)
            if direction == "LONG"
            else liquidity.pools_below(entry, g.tf)
        )
        pools = [
            p
            for p in pools
            if self.trade.min_tp_distance_atr * atr
            <= abs(p.level - entry)
            <= self.trade.max_tp_search_atr * atr
        ]
        if not pools:
            self.reject("NO_TARGET_IN_RANGE", g.tf)
            return None
        tp_pool = pools[0]
        eq_distance = abs(eq - entry)
        eq_in_direction = (direction == "LONG" and eq > entry) or (direction == "SHORT" and eq < entry)
        eq_eligible = eq_in_direction and eq_distance >= self.trade.min_tp_distance_atr * atr
        target_kind = (
            "EQUILIBRIUM" if eq_eligible and eq_distance <= abs(tp_pool.level - entry) else "POOL"
        )
        target = eq if target_kind == "EQUILIBRIUM" else tp_pool.level
        reward_r = abs(target - entry) / risk
        if reward_r < self.trade.min_r:
            self.reject("R_BELOW_MIN", g.tf)
            return None
        if reward_r > self.trade.max_tp_r:
            self.reject("TARGET_BEYOND_MAX_R", g.tf)
            return None
        active_calls = [c for c in active if c.state == "ACTIVE"]
        pending_calls = [c for c in active if c.state == "PENDING"]
        if len(pending_calls) >= self.calls.max_pending:
            self.reject("PENDING_TOTAL", g.tf)
            return None
        if len(active_calls) >= self.calls.max_concurrent:
            self.reject("CONCURRENT_TOTAL", g.tf)
            return None
        if any(c.direction == direction and c.timeframe == g.tf for c in active_calls):
            self.reject("CONCURRENT_SAME_TF", g.tf)
            return None
        if any(
            c.direction == direction and max(c.entry_lo, lo) <= min(c.entry_hi, hi) + 0.5 * atr
            for c in active_calls
        ):
            self.reject("CORRELATED_ZONE", g.tf)
            return None
        opposing = [c for c in active_calls if c.direction != direction]
        if opposing:
            self.reject("OPPOSING_HTF_CALL", g.tf)
            return None
        ote_lo, ote_hi = (
            (low + 0.618 * (high - low), low + 0.79 * (high - low))
            if direction == "SHORT"
            else (high - 0.79 * (high - low), high - 0.618 * (high - low))
        )
        created = bar.t_open_ms + timeframe_ms(bar.tf)
        call = Call(
            created_ms=created,
            kind="SETUP",
            direction=direction,
            entry_lo=lo,
            entry_hi=hi,
            entry_ref=entry,
            invalidation=stop,
            target=target,
            expires_ms=created + self.trade.call_expiry_bars * timeframe_ms(bar.tf),
            state_hash=content_hash((bar.id, structure.model_dump(), ob.id)),
            reason=f"{event.kind} Â· {g.tf} OB Â· {target_kind.lower()} target",
            reason_chain=(
                f"{event.kind} body close",
                f"{g.tf} OB confirmed",
                "Dealing range equilibrium target"
                if target_kind == "EQUILIBRIUM"
                else f"{tp_pool.geometry.name} target",
            ),
            grade=grade,
            grade_notes=tuple(grade_notes),
            symbol=bar.symbol,
            clock_version=clock_version,
            timeframe=g.tf,
            tp2=(
                tp_pool.level
                if target_kind == "EQUILIBRIUM"
                else pools[1].level
                if len(pools) > 1
                else None
            ),
            in_ote=ote_lo <= entry <= ote_hi,
            ob_id=ob.id,
            structure_event_id=event.id,
            target_pool_id=tp_pool.id,
            source_bars=g.source_bars,
        )
        self.used_zones.add(ob.id)
        return call

    def mark_resolution(self, call: Call) -> None:
        if call.state == "LOSS" and call.ob_id:
            self.spent_zones.add(call.ob_id)

    def can_activate(self, candidate: Call, calls: list[Call]) -> bool:
        """Apply exposure limits when a published pending call actually fills."""
        active = [call for call in calls if call.state == "ACTIVE" and call.id != candidate.id]
        if len(active) >= self.calls.max_concurrent:
            return False
        if (
            sum(
                call.direction == candidate.direction and call.timeframe == candidate.timeframe
                for call in active
            )
            >= self.calls.max_per_direction_per_tf
        ):
            return False
        return self.calls.allow_opposing_concurrent or not any(
            call.direction != candidate.direction for call in active
        )





