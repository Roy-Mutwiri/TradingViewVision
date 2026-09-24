"""Deterministic liquidity registry. Wicks raid; closed bodies accept or reclaim.

Named levels consume confirmed M1 through the shared analytical calendar and
ribbon sessions. Equality holds a pending raid, so its bar deadline can expire.
All thresholds freeze at creation. No wall clock or view state enters this module.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Literal, cast

from oracle.candidates.contracts import Decision, EvalPoint, Measurement
from oracle.config import LiquidityConfig, SessionsConfig, StructureConfig
from oracle.data.analytical_days import trading_day_bounds, trading_week_bounds
from oracle.data.sessions import session_intervals
from oracle.indicators.ut_bot import ATRState, rma_atr
from oracle.models import Bar, Timeframe, timeframe_ms
from oracle.smc.liquidity_contracts import LiquidityGeometry, Pool, Sweep, SweepCandidate
from oracle.smc.structure import StructureCursor, advance_structure
from oracle.smc.swing_contracts import SwingSnapshot
from oracle.smc.swings import SwingConfig


def identity(value: object) -> str:
    return hashlib.blake2b(json.dumps(value, sort_keys=True).encode(), digest_size=8).hexdigest()


class NamedCalendar:
    def __init__(self, sessions: SessionsConfig):
        self.sessions = sessions
        self.last_ms = -1
        self.first_ms: int | None = None
        self.days: dict[int, tuple[Bar, Bar, Bar]] = {}
        self.weeks: dict[int, tuple[Bar, Bar, Bar]] = {}
        self.sessions_seen: dict[tuple[str, int], tuple[Bar, Bar, Bar]] = {}

    @staticmethod
    def add(mapping: dict, key: object, b: Bar) -> None:
        old = mapping.get(key)
        mapping[key] = (
            (b, b, b)
            if old is None
            else (old[0] if old[0].h >= b.h else b, old[1] if old[1].l <= b.l else b, old[2])
        )

    def consume(self, minutes: Sequence[Bar], at: int) -> None:
        for b in minutes:
            if b.tf != "M1" or not b.complete or b.source != "mt5":
                raise ValueError("LIQUIDITY_REQUIRES_CONFIRMED_MT5_M1")
            if b.t_open_ms + 60000 > at:
                raise ValueError("LIQUIDITY_FUTURE_M1")
            if b.t_open_ms <= self.last_ms:
                continue
            self.last_ms = b.t_open_ms
            if self.first_ms is None:
                self.first_ms = b.t_open_ms
            day, _ = trading_day_bounds(b.t_open_ms, self.sessions.day_boundary)
            week, _ = trading_week_bounds(b.t_open_ms, self.sessions.day_boundary)
            self.add(self.days, day, b)
            self.add(self.weeks, week, b)
            for s in session_intervals(b.t_open_ms):
                if s.start_ms <= b.t_open_ms < s.end_ms:
                    self.add(self.sessions_seen, (s.key, s.start_ms), b)

    def levels(self, at: int) -> list[tuple[str, str, Bar, int, str]]:
        day, _ = trading_day_bounds(at, self.sessions.day_boundary)
        week, _ = trading_week_bounds(at, self.sessions.day_boundary)
        pd = max((d for d in self.days if d < day), default=None)
        pw = max((w for w in self.weeks if w < week), default=None)
        result = []
        for key, start, values in [
            ("PD", pd, self.days.get(pd) if pd is not None else None),
            ("PW", pw, self.weeks.get(pw) if pw is not None else None),
            ("D", day, self.days.get(day)),
        ]:
            if start is None or values is None:
                continue
            if key == "PW" and (self.first_ms is None or self.first_ms > start):
                continue
            for side, b in [("HIGH", values[0]), ("LOW", values[1])]:
                name = key + ("H" if side == "HIGH" else "L")
                result.append((name, side, b, start, f"{name}:{week if key == 'PW' else day}"))
        for s in session_intervals(at):
            values = self.sessions_seen.get((s.key, s.start_ms))
            if values:
                for side, b in [("HIGH", values[0]), ("LOW", values[1])]:
                    name = f"{s.key} {'H' if side == 'HIGH' else 'L'}"
                    result.append((name, side, b, s.start_ms, f"{name}:{s.start_ms}"))
        return result


class LiquidityEngine:
    def __init__(
        self,
        tf: Timeframe,
        config: LiquidityConfig = LiquidityConfig(),
        sessions: SessionsConfig = SessionsConfig(),
    ):
        self.tf, self.config = tf, config
        self.calendar = NamedCalendar(sessions)
        self.pools: dict[str, Pool] = {}
        self.active: set[str] = set()
        self.named: dict[str, str] = {}
        self.pair_ids: set[str] = set()
        self.pending: dict[str, str] = {}
        self.candidates: dict[str, SweepCandidate] = {}
        self.sweeps: tuple[Sweep, ...] = ()
        self.decisions: list[Decision] = []
        self.current_atr: float | None = None

    def emit(
        self,
        p: EvalPoint,
        oid: str,
        g: LiquidityGeometry,
        action: str,
        at: int,
        *,
        kind: str = "POOL",
        reason: str | None = None,
        criterion: str | None = None,
        confirmed_id: str | None = None,
        measurement: Measurement | None = None,
    ) -> Decision:
        d = Decision.model_validate(
            dict(
                seq=p.seq,
                t_broker_ms=p.t_broker_ms,
                t_utc_ms=at,
                object_id=oid,
                kind=kind,
                action=action,
                reason=reason,
                criterion=criterion,
                confirmed_id=confirmed_id,
                fidelity=p.fidelity,
                tf=self.tf,
                geometry=g,
                source_bars=g.source_bars,
                source_object_ids=g.source_object_ids,
                measurement=measurement,
            )
        )
        self.decisions.append(d)
        return d

    def discard(self, c: SweepCandidate, p: EvalPoint, at: int, reason: str) -> None:
        d = self.emit(p, c.id, c.geometry, "DISCARD", at, kind="SWEEP", reason=reason)
        self.candidates[c.id] = c.model_copy(
            update=dict(state="DISCARDED", reason=reason, decision_id=d.id)
        )
        self.pending.pop(c.pool_id, None)

    def retire(self, oid: str, p: EvalPoint, at: int) -> None:
        self.emit(p, oid, self.pools[oid].geometry, "UPDATE", at, criterion="PERIOD_SUPERSEDED")
        c = self.candidates.get(self.pending.get(oid, ""))
        if c is None:
            self.active.discard(oid)
        # A newly computed running extreme cannot erase an unresolved raid.
        # Its old geometry remains active until the original close-based ruling.

    def named_levels(self, p: EvalPoint, at: int, atr: float, minutes: Sequence[Bar]) -> None:
        self.calendar.consume(minutes, at)
        desired = set()
        for name, side, b, start, scope in self.calendar.levels(at):
            if name.split()[0] not in self.config.named_levels:
                continue
            desired.add(name)
            level = b.h if side == "HIGH" else b.l
            prior = self.named.get(name)
            if prior and self.pools[prior].scope_key == scope and self.pools[prior].level == level:
                continue
            if prior:
                self.retire(prior, p, at)
            g = LiquidityGeometry(
                tf=self.tf,
                direction="BEARISH" if side == "HIGH" else "BULLISH",
                side=cast(Literal["HIGH", "LOW"], side),
                name=name,
                level=level,
                price_lo=level,
                price_hi=level,
                ce=level,
                atr_at_creation=atr,
                created_ms=at,
                t_start_ms=start,
                source_bars=(b.t_open_ms // 60000,),
                source_object_ids=(b.id,),
            )
            oid = identity((self.tf, name, scope, b.id, level))
            self.pools[oid] = Pool(
                id=oid,
                geometry=g,
                strength=1,
                named=True,
                scope_key=scope,
                touch_times=(b.t_open_ms,),
            )
            self.active.add(oid)
            self.named[name] = oid
            self.emit(p, oid, g, "CREATE", at, criterion="M1_NAMED_LEVEL")
        for name in sorted(set(self.named) - desired):
            self.retire(self.named.pop(name), p, at)

    def equal_pools(self, snapshot: SwingSnapshot, p: EvalPoint, idx: int, at: int) -> None:
        pivots = {x.id: x for x in snapshot.internal if x.confirmed}
        for pair in snapshot.equal_pairs:
            if pair.id in self.pair_ids:
                continue
            ps = [pivots[oid] for oid in pair.pivot_ids if oid in pivots]
            if len(ps) < 2 or any(
                x.confirmed_at_idx is None or x.confirmed_at_idx > idx for x in ps
            ):
                continue
            atr = snapshot.atr[-1]
            if atr is None or atr <= 0:
                continue
            self.pair_ids.add(pair.id)
            if (
                max(x.price for x in ps) - min(x.price for x in ps)
                > self.config.eq_tolerance_atr * atr
            ):
                continue
            side = "HIGH" if pair.kind == "EQH" else "LOW"
            level = max(x.price for x in ps) if side == "HIGH" else min(x.price for x in ps)
            members = {x.id for x in ps}
            for oid in sorted(self.active):
                prior = self.pools[oid]
                if not prior.named and set(prior.geometry.source_object_ids) < members:
                    self.retire(oid, p, at)
            g = LiquidityGeometry(
                tf=self.tf,
                direction="BEARISH" if side == "HIGH" else "BULLISH",
                side=cast(Literal["HIGH", "LOW"], side),
                name=pair.kind,
                level=level,
                price_lo=level,
                price_hi=level,
                ce=level,
                atr_at_creation=atr,
                created_ms=at,
                t_start_ms=min(x.t_ms for x in ps),
                source_bars=tuple(x.idx for x in ps),
                source_object_ids=tuple(x.id for x in ps),
            )
            oid = identity((self.tf, pair.kind, sorted(members), level))
            self.pools[oid] = Pool(
                id=oid,
                geometry=g,
                strength=len(ps),
                touch_bars=tuple(x.idx for x in ps),
                touch_times=tuple(x.t_ms for x in ps),
            )
            self.active.add(oid)
            self.emit(p, oid, g, "CREATE", at, criterion="EQUAL_CONFIRMED_PIVOTS")

    def process(
        self,
        p: EvalPoint,
        b: Bar,
        idx: int,
        at: int,
        atr: float | None,
        *,
        minutes: Sequence[Bar] = (),
        data_gap: bool = False,
        allow_birth: bool = True,
    ) -> list[Decision]:
        before = len(self.decisions)
        if not data_gap:
            self.calendar.consume(minutes, at)
            if atr is not None and atr > 0:
                self.current_atr = atr
        for oid in sorted(self.active):
            pool = self.pools[oid]
            if pool.state == "BROKEN" or (pool.state == "SWEPT" and p.bar_phase != "CLOSE"):
                continue
            g = pool.geometry
            high = g.side == "HIGH"
            pending = self.candidates.get(self.pending.get(oid, ""))
            if data_gap:
                if pending:
                    self.discard(pending, p, at, "DATA_GAP")
                continue
            extreme = (
                (b.h if high else b.l)
                if p.bar_phase == "CLOSE" and g.created_ms <= b.t_open_ms
                else p.price
            )
            penetration = extreme - g.level if high else g.level - extreme
            raid_atr = atr if atr is not None and atr > 0 else g.atr_at_creation
            threshold = self.config.sweep_min_penetration_atr * raid_atr
            new_touch = not any(
                b.t_open_ms <= t < b.t_open_ms + timeframe_ms(self.tf) for t in pool.touch_times
            )
            if (
                penetration >= 0
                and pool.state in ("FRESH", "TOUCHED")
                and (pool.state == "FRESH" or new_touch)
            ):
                pool = pool.model_copy(
                    update=dict(
                        state="TOUCHED",
                        strength=pool.strength + int(new_touch),
                        touch_bars=(*pool.touch_bars, idx),
                        touch_times=(*pool.touch_times, b.t_open_ms),
                    )
                )
                self.pools[oid] = pool
                self.emit(p, oid, g, "UPDATE", at, criterion="TOUCHED")
            if (
                pending is None
                and pool.state != "SWEPT"
                and penetration >= threshold
                and allow_birth
            ):
                cid = identity((oid, p.seq, idx, "SWEEP"))
                raid_geometry = g.model_copy(update={"atr_at_creation": raid_atr, "created_ms": at})
                m = Measurement(
                    price_a=g.level,
                    price_b=extreme,
                    value=penetration / raid_atr,
                    unit="ATR",
                    criterion="SWEEP_PENETRATION",
                    threshold=self.config.sweep_min_penetration_atr,
                    passed=True,
                )
                d = self.emit(p, cid, raid_geometry, "CREATE", at, kind="SWEEP", measurement=m)
                pending = SweepCandidate(
                    id=cid,
                    pool_id=oid,
                    geometry=raid_geometry,
                    born_bar_idx=idx,
                    born_seq=p.seq,
                    penetration_atr=penetration / raid_atr,
                    threshold_at_creation=threshold,
                    extreme=extreme,
                    fidelity=p.fidelity,
                    decision_id=d.id,
                )
                self.candidates[cid] = pending
                self.pending[oid] = cid
            if pending:
                ex = max(pending.extreme, extreme) if high else min(pending.extreme, extreme)
                if ex != pending.extreme:
                    d = self.emit(
                        p,
                        pending.id,
                        pending.geometry,
                        "UPDATE",
                        at,
                        kind="SWEEP",
                        criterion="RAID_EXTREME",
                    )
                    pending = pending.model_copy(update=dict(extreme=ex, decision_id=d.id))
                    self.candidates[pending.id] = pending
            if p.bar_phase != "CLOSE":
                continue
            beyond = b.c > g.level if high else b.c < g.level
            if beyond:
                if pending:
                    self.discard(pending, p, at, "INVALIDATED")
                self.pools[oid] = pool.model_copy(update={"state": "BROKEN"})
                self.active.discard(oid)
                self.emit(p, oid, g, "UPDATE", at, criterion="BODY_ACCEPTANCE")
            elif pending and (b.c < g.level if high else b.c > g.level):
                s = Sweep(
                    id=identity((pending.id, b.id, "RECLAIM")),
                    pool_id=oid,
                    timeframe=self.tf,
                    side=g.side,
                    level=g.level,
                    extreme=pending.extreme,
                    penetration_bar_idx=pending.born_bar_idx,
                    confirmed_bar_idx=idx,
                    reclaim_bar_idx=idx,
                    confirmed_ms=at,
                    reclaim_ms=at,
                    atr_at_creation=pending.geometry.atr_at_creation,
                    fidelity=p.fidelity,
                    source_bars=tuple(range(pending.born_bar_idx, idx + 1)),
                    source_object_ids=(*g.source_object_ids, b.id),
                )
                self.sweeps = (*self.sweeps, s)
                d = self.emit(
                    p, pending.id, pending.geometry, "PROMOTE", at, kind="SWEEP", confirmed_id=s.id
                )
                self.candidates[pending.id] = pending.model_copy(
                    update=dict(state="PROMOTED", decision_id=d.id)
                )
                self.pending.pop(oid, None)
                self.pools[oid] = pool.model_copy(
                    update=dict(state="SWEPT", swept_ms=at, sweep_event_id=s.id)
                )
                self.emit(p, oid, g, "UPDATE", at, criterion="SWEPT", confirmed_id=s.id)
            elif pending and idx - pending.born_bar_idx + 1 >= self.config.sweep_reclaim_bars:
                self.discard(pending, p, at, "STALE")
        # Named levels derive only from confirmed M1 input and calendar
        # boundaries. Synthetic O/L/H traversal points cannot change them.
        if (
            not data_gap
            and atr is not None
            and atr > 0
            and (minutes or p.bar_phase == "CLOSE")
        ):
            self.named_levels(p, at, atr, ())
        return self.decisions[before:]

    def sweep_query(self, tf: str, idx: int, lookback: int, direction: str) -> str | None:
        side = "LOW" if direction == "UP" else "HIGH"
        return next(
            (
                s.id
                for s in reversed(self.sweeps)
                if s.timeframe == tf
                and s.side == side
                and 0 < idx - s.confirmed_bar_idx <= lookback
            ),
            None,
        )

    def pools_above(self, price: float, tf: str) -> list[Pool]:
        return sorted(
            (
                self.pools[oid]
                for oid in self.active
                if self.pools[oid].geometry.tf == tf
                and self.pools[oid].state in ("FRESH", "TOUCHED")
                and self.pools[oid].level > price
            ),
            key=lambda p: (p.level - price, -p.strength, p.id),
        )

    def pools_below(self, price: float, tf: str) -> list[Pool]:
        return sorted(
            (
                self.pools[oid]
                for oid in self.active
                if self.pools[oid].geometry.tf == tf
                and self.pools[oid].state in ("FRESH", "TOUCHED")
                and self.pools[oid].level < price
            ),
            key=lambda p: (price - p.level, -p.strength, p.id),
        )


def liquidity(
    bars: Sequence[Bar],
    minutes: Sequence[Bar] = (),
    config: LiquidityConfig = LiquidityConfig(),
    sessions: SessionsConfig = SessionsConfig(),
    structure_config: StructureConfig = StructureConfig(),
    swing_config: SwingConfig | None = None,
) -> tuple[LiquidityEngine, StructureCursor | None]:
    if not bars:
        raise ValueError("LIQUIDITY_REQUIRES_BARS")
    engine = LiquidityEngine(bars[0].tf, config, sessions)
    cursor = None
    atr = ATRState(14)
    mi = 0
    for idx, b in enumerate(bars):
        if not b.complete:
            raise ValueError("LIQUIDITY_CONFIRMED_PREFIX_ONLY")
        at = b.t_open_ms + timeframe_ms(b.tf)
        values, atr = rma_atr((b,), 14, state=atr, with_state=True)
        available = []
        while mi < len(minutes) and minutes[mi].t_open_ms + 60000 <= at:
            available.append(minutes[mi])
            mi += 1
        p = EvalPoint(
            seq=idx,
            t_broker_ms=at,
            price=b.c,
            bar_index=idx,
            bar_phase="CLOSE",
            source="BAR_COARSE",
            fidelity="BAR",
        )
        engine.process(p, b, idx, at, values[0], minutes=available)
        cursor = advance_structure(
            cursor, b, structure_config, swing_config=swing_config, sweep_query=engine.sweep_query
        )
        if cursor:
            engine.equal_pools(cursor.swings.snapshot, p, idx, at)
    return engine, cursor
