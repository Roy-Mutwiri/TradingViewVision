"""EvalPoint-only lifecycle; hypothetical closes reuse the existing FVG predicate.

Tentative geometry is contained exclusively by CandidateObject. Only a CLOSE
point, checked against the authoritative closed bar, creates an FVGRecord.
"""

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import replace

from oracle.candidates.contracts import (
    CandidateObject,
    Decision,
    DiscardReason,
    EvalPoint,
    Measurement,
)
from oracle.config import LiquidityConfig, SessionsConfig, StructureConfig, ZonesConfig
from oracle.indicators.ut_bot import ATRState, rma_atr
from oracle.models import Bar, Timeframe, timeframe_ms
from oracle.smc.imbalance import (
    FVGGeometry,
    FVGRecord,
    ImbalanceCursor,
    advance_imbalance,
    create_fvg_record,
    detect_fvg,
)
from oracle.smc.liquidity import LiquidityEngine
from oracle.smc.order_blocks import OrderBlockEngine
from oracle.smc.structure import advance_structure
from oracle.smc.swings import SwingConfig

logger = logging.getLogger(__name__)


def confirmed_only(value: FVGRecord) -> FVGRecord:
    if not isinstance(value, FVGRecord):
        raise TypeError("CALL_REQUIRES_CONFIRMED_OBJECT")
    return value


class CandidateEngine:
    def __init__(
        self,
        tf: Timeframe,
        seed: Sequence[Bar],
        config: ZonesConfig,
        *,
        ttl_bars: int = 3,
        offset_s: int = 0,
        initial_partial_bar: bool = False,
        order_blocks_enabled: bool = False,
        structure_config: StructureConfig = StructureConfig(),
        swing_config: SwingConfig | None = None,
        liquidity_enabled: bool = False,
        liquidity_config: LiquidityConfig = LiquidityConfig(),
        sessions_config: SessionsConfig = SessionsConfig(),
        seed_minutes: Sequence[Bar] = (),
    ) -> None:
        self.tf, self.config, self.ttl, self.offset_s = tf, config, ttl_bars, offset_s
        self.initial_partial_bar = initial_partial_bar
        self.structure_config = structure_config
        self.swing_config = swing_config
        self.atr = ATRState(14)
        self.cursor = ImbalanceCursor(config=config)
        self.closed: list[Bar] = []
        self.seed_minutes = list(seed_minutes)
        self.liquidity = (
            LiquidityEngine(tf, liquidity_config, sessions_config) if liquidity_enabled else None
        )
        self.liquidity_structure = None
        minute_index = 0
        self.ob = (
            OrderBlockEngine(config, structure_config, swing_config)
            if order_blocks_enabled
            else None
        )
        for bar in seed:
            if not bar.complete or bar.tf != tf:
                raise ValueError("candidate seed requires closed bars of its own timeframe")
            self.cursor = advance_imbalance(self.cursor, bar)
            self.atr = self.cursor.atr_state
            if self.liquidity:
                p = EvalPoint(
                    seq=len(self.closed),
                    t_broker_ms=bar.t_open_ms + timeframe_ms(tf) + offset_s * 1000,
                    price=bar.c,
                    bar_index=len(self.closed),
                    bar_phase="CLOSE",
                    source="BAR_COARSE",
                    fidelity="BAR",
                )
                available = []
                while minute_index < len(seed_minutes) and seed_minutes[
                    minute_index
                ].t_open_ms + 60000 <= bar.t_open_ms + timeframe_ms(tf):
                    available.append(seed_minutes[minute_index])
                    minute_index += 1
                self.liquidity.process(
                    p,
                    bar,
                    len(self.closed),
                    bar.t_open_ms + timeframe_ms(tf),
                    self.atr.value,
                    minutes=available,
                )
            if self.ob:
                p = EvalPoint(
                    seq=len(self.closed),
                    t_broker_ms=bar.t_open_ms + timeframe_ms(tf) + offset_s * 1000,
                    price=bar.c,
                    bar_index=len(self.closed),
                    bar_phase="CLOSE",
                    source="BAR_COARSE",
                    fidelity="BAR",
                )
                self.ob.process(
                    p,
                    self.closed,
                    bar,
                    self.atr.value,
                    [
                        r.geometry
                        for r in self.cursor.records
                        if r.kind == "FVG"
                        and r.geometry.created_idx >= max(0, len(self.closed) - config.ob_max_leg_bars)
                    ],
                    at_ms=bar.t_open_ms + timeframe_ms(tf),
                    sweep_query=self.liquidity.sweep_query if self.liquidity else None,
                )
            if self.liquidity:
                cursor = (
                    self.ob.structure
                    if self.ob
                    else advance_structure(
                        self.liquidity_structure,
                        bar,
                        structure_config,
                        swing_config=swing_config,
                        sweep_query=self.liquidity.sweep_query,
                    )
                )
                self.liquidity_structure = cursor
                if cursor:
                    self.liquidity.equal_pools(
                        cursor.swings.snapshot,
                        p,
                        len(self.closed),
                        bar.t_open_ms + timeframe_ms(tf),
                    )
            self.closed.append(bar)
        self.liquidity_seed_decisions = list(self.liquidity.decisions) if self.liquidity else []
        if self.liquidity:
            self.liquidity.candidates = {
                oid: c for oid, c in self.liquidity.candidates.items() if c.state == "CANDIDATE"
            }
            self.liquidity.decisions.clear()
        self.liquidity_bootstrap_pending = bool(self.liquidity and self.liquidity.pending)
        self.ob_seed_decisions = list(self.ob.decisions) if self.ob else []
        self.ob_seed_rejections = list(self.ob.rejections) if self.ob else []
        if self.ob:
            self.ob.candidates = {
                oid: c for oid, c in self.ob.candidates.items() if c.state == "CANDIDATE"
            }
            self.ob.decisions.clear()
            self.ob.rejections.clear()
            self.ob.rejection_keys.clear()
            self.ob.records = tuple(r.model_copy(update={"last_seq": -1}) for r in self.ob.records)
        self.ob_bootstrap_pending = bool(self.ob and self.ob.candidates)
        self.candidates: dict[str, CandidateObject] = {}
        self.active_candidates: set[str] = set()
        self.confirmed: list[FVGRecord] = []
        self.decisions: list[Decision] = []
        self.last_seq = -1
        self.last_index = -1
        self.closed_indices: set[int] = set()
        self.forming: Bar | None = None

    def _emit(
        self,
        point: EvalPoint,
        candidate: CandidateObject,
        action: str,
        *,
        reason: DiscardReason | None = None,
        criterion: str | None = None,
        confirmed_id: str | None = None,
    ) -> CandidateObject:
        gap = candidate.geometry
        value = gap.size / gap.atr_at_creation
        measurement = None
        if action in ("CREATE", "UPDATE"):
            measurement = Measurement(
                price_a=gap.price_lo,
                price_b=gap.price_hi,
                value=gap.size,
                unit="pts",
                criterion="GAP_PRESENT",
                threshold=0,
                passed=gap.size > 0,
            )
        elif action == "PROMOTE" or criterion == "FVG_SIZE":
            measurement = Measurement(
                price_a=gap.price_lo,
                price_b=gap.price_hi,
                value=value,
                unit="ATR",
                criterion="FVG_SIZE",
                threshold=self.config.fvg_min_atr,
                passed=value >= self.config.fvg_min_atr,
            )
        decision = Decision.model_validate(
            dict(
                seq=point.seq,
                t_broker_ms=point.t_broker_ms,
                object_id=candidate.id,
                kind="FVG",
                action=action,
                reason=reason,
                fidelity=point.fidelity,
                tf=self.tf,
                t_utc_ms=point.t_broker_ms - self.offset_s * 1000,
                criterion=criterion,
                confirmed_id=confirmed_id,
                geometry=gap,
                source_bars=gap.source_bars,
                source_object_ids=gap.source_object_ids,
                measurement=measurement,
            )
        )
        self.decisions.append(decision)
        state = (
            "PROMOTED"
            if action == "PROMOTE"
            else "DISCARDED"
            if action == "DISCARD"
            else "CANDIDATE"
        )
        result = candidate.model_copy(
            update={
                "state": state,
                "reason": reason,
                "criterion": criterion,
                "decision_id": decision.id,
            }
        )
        self.candidates[result.id] = result
        if state == "CANDIDATE":
            self.active_candidates.add(result.id)
        else:
            self.active_candidates.discard(result.id)
        return result

    def process(
        self,
        point: EvalPoint,
        *,
        parent_open_ms: int,
        closed_bar: Bar | None = None,
        data_gap: bool = False,
        closed_minutes: Sequence[Bar] = (),
    ) -> list[Decision]:
        if point.seq != self.last_seq + 1:
            raise ValueError("EvalPoint seq must start at zero, increase and never be reused")
        if point.bar_index < self.last_index or point.bar_index in self.closed_indices:
            raise ValueError("CLOSE must be the last point for a bar")
        if point.bar_phase != "CLOSE" and closed_bar is not None:
            raise ValueError("authoritative close supplied at a non-CLOSE point")
        at_utc = point.t_broker_ms - self.offset_s * 1000
        end_ms = parent_open_ms + timeframe_ms(self.tf)
        if point.bar_phase == "CLOSE":
            if at_utc != end_ms:
                raise ValueError("CLOSE must occur at the true parent bar end")
        elif not parent_open_ms <= at_utc < end_ms:
            raise ValueError("EvalPoint must lie inside its parent bar")
        before = len(self.decisions)
        if self.liquidity and self.liquidity_bootstrap_pending:
            for c in self.liquidity.candidates.values():
                self.decisions.append(
                    self.liquidity.emit(
                        point,
                        c.id,
                        c.geometry,
                        "CREATE",
                        at_utc,
                        kind="SWEEP",
                        criterion="CARRY_IN",
                    )
                )
            self.liquidity_bootstrap_pending = False
        if self.ob and self.ob_bootstrap_pending:
            for ob_candidate in tuple(self.ob.candidates.values()):
                self.ob.emit(point, ob_candidate, "CREATE", at_utc, criterion="CARRY_IN")
            self.decisions.extend(self.ob.decisions)
            self.ob_bootstrap_pending = False
        self.last_seq, self.last_index = point.seq, point.bar_index
        for candidate_id in sorted(self.active_candidates):
            stale_candidate = self.candidates[candidate_id]
            if data_gap:
                self._emit(point, stale_candidate, "DISCARD", reason="DATA_GAP")
            elif point.bar_index - stale_candidate.born_bar_index >= self.ttl:
                logger.warning("CANDIDATE_BACKSTOP_STALE kind=FVG id=%s tf=%s", stale_candidate.id, self.tf)
                self._emit(point, stale_candidate, "DISCARD", reason="STALE")
        if self.forming is None or self.forming.t_open_ms != parent_open_ms:
            self.forming = Bar(
                tf=self.tf,
                t_open_ms=parent_open_ms,
                o=point.price,
                h=point.price,
                l=point.price,
                c=point.price,
                tick_volume=1,
                source="mt5",
                complete=False,
                digits=self.closed[-1].digits if self.closed else 3,
            )
        else:
            self.forming = Bar.model_validate(
                self.forming.model_dump()
                | dict(
                    h=max(self.forming.h, point.price),
                    l=min(self.forming.l, point.price),
                    c=point.price,
                    id="",
                    object_hash="",
                )
            )
        bar = self.forming.transition(complete=True)
        if closed_bar is not None:
            if (
                not closed_bar.complete
                or closed_bar.tf != self.tf
                or closed_bar.t_open_ms != parent_open_ms
            ):
                raise ValueError("CLOSE needs the matching confirmed parent bar")
            if point.price != closed_bar.c:
                raise ValueError("CLOSE price must be the true parent close")
            bar = closed_bar
        atr = rma_atr([bar], 14, state=self.atr)[0]
        if self.liquidity:
            self.decisions.extend(
                self.liquidity.process(
                    point,
                    bar,
                    len(self.closed),
                    at_utc,
                    atr,
                    minutes=closed_minutes,
                    data_gap=data_gap,
                    allow_birth=not (
                        self.initial_partial_bar
                        and point.bar_index == 0
                        and point.bar_phase != "CLOSE"
                    ),
                )
            )
        tentative: FVGGeometry | None = None
        missing_prefix = (
            self.initial_partial_bar
            and point.bar_index == 0
            and not (point.bar_phase == "CLOSE" and closed_bar is not None)
        )
        if len(self.closed) >= 2 and atr is not None and not data_gap and not missing_prefix:
            tentative = detect_fvg(
                [*self.closed[-2:], bar],
                atr=atr,
                start_idx=len(self.closed) - 2,
                config=self.config.model_copy(update={"fvg_min_atr": 0}),
            )
        current = [
            self.candidates[candidate_id]
            for candidate_id in sorted(self.active_candidates)
            if self.candidates[candidate_id].born_bar_index == point.bar_index
        ]
        candidate: CandidateObject | None = current[0] if current else None
        if candidate is not None and tentative is None:
            candidate = self._emit(
                point, candidate, "DISCARD", reason="INVALIDATED", criterion="GAP_FILLED"
            )
        elif tentative is not None:
            if candidate is None:
                identity = (
                    "XAUUSD",
                    self.tf,
                    parent_open_ms,
                    tentative.direction,
                    point.seq,
                    tentative.price_lo,
                    tentative.price_hi,
                )
                candidate = CandidateObject(
                    id=hashlib.blake2b(repr(identity).encode(), digest_size=8).hexdigest(),
                    geometry=tentative,
                    born_seq=point.seq,
                    born_bar_index=point.bar_index,
                    fidelity=point.fidelity,
                    decision_id="pending",
                )
                candidate = self._emit(point, candidate, "CREATE")
            elif candidate.geometry != tentative:
                # ATR/close source provenance changes alone are not geometry changes.
                changed = (candidate.geometry.price_lo, candidate.geometry.price_hi) != (
                    tentative.price_lo,
                    tentative.price_hi,
                )
                candidate = candidate.model_copy(update={"geometry": tentative})
                self.candidates[candidate.id] = candidate
                if changed:
                    candidate = self._emit(point, candidate, "UPDATE")
        if point.bar_phase == "CLOSE":
            if data_gap and closed_bar is None:
                if self.ob:
                    self.decisions.extend(
                        self.ob.process(
                            point, self.closed, bar, atr, [], at_ms=at_utc, data_gap=True
                        )
                    )
                # A bucket's last price is not an authoritative missing OHLC bar.
                self.closed_indices.add(point.bar_index)
                self.forming = None
                return self.decisions[before:]
            if candidate is not None and candidate.state == "CANDIDATE":
                geometry = detect_fvg(
                    [*self.closed[-2:], bar],
                    atr=atr,
                    start_idx=len(self.closed) - 2,
                    config=self.config,
                )
                if geometry is None:
                    self._emit(
                        point, candidate, "DISCARD", reason="FAILED_CRITERIA", criterion="FVG_SIZE"
                    )
                else:
                    candidate = candidate.model_copy(update={"geometry": geometry})
                    record = create_fvg_record(geometry).model_copy(
                        update={"fidelity": point.fidelity}
                    )
                    self.confirmed.append(record)
                    self._emit(point, candidate, "PROMOTE", confirmed_id=record.id)
            self.cursor = advance_imbalance(self.cursor, bar)
            self.cursor = replace(
                self.cursor,
                records=tuple(
                    r.model_copy(update={"fidelity": point.fidelity})
                    if r.born_ms == at_utc and r.fidelity != point.fidelity
                    else r
                    for r in self.cursor.records
                ),
            )
            self.atr = self.cursor.atr_state
            if self.ob:
                self.decisions.extend(
                    self.ob.process(
                        point,
                        self.closed,
                        bar,
                        atr,
                        [
                            r.geometry
                            for r in self.cursor.records
                            if r.kind == "FVG"
                            and r.geometry.created_idx
                            >= max(0, len(self.closed) - self.config.ob_max_leg_bars)
                        ],
                        at_ms=at_utc,
                        data_gap=data_gap,
                        sweep_query=self.liquidity.sweep_query if self.liquidity else None,
                    )
                )
            self.closed.append(bar)
            if self.liquidity:
                prior = len(self.liquidity.decisions)
                cursor = (
                    self.ob.structure
                    if self.ob
                    else advance_structure(
                        self.liquidity_structure,
                        bar,
                        self.structure_config,
                        swing_config=self.swing_config,
                        sweep_query=self.liquidity.sweep_query,
                    )
                )
                self.liquidity_structure = cursor
                if cursor:
                    self.liquidity.equal_pools(
                        cursor.swings.snapshot, point, len(self.closed) - 1, at_utc
                    )
                self.decisions.extend(self.liquidity.decisions[prior:])
            self.closed_indices.add(point.bar_index)
            self.forming = None
        elif self.ob:
            # The OB validator cannot consume an imbalance older than its
            # bounded leg. Passing the complete historical registry here made
            # long replays increasingly expensive with no possible decision
            # difference.
            gaps = [
                r.geometry
                for r in self.cursor.records
                if r.kind == "FVG"
                and r.geometry.created_idx
                >= max(0, len(self.closed) - self.config.ob_max_leg_bars)
            ]
            if tentative and tentative.size >= self.config.fvg_min_atr * tentative.atr_at_creation:
                gaps.append(tentative)
            self.decisions.extend(
                self.ob.process(
                    point,
                    self.closed,
                    bar,
                    atr,
                    gaps,
                    at_ms=at_utc,
                    data_gap=data_gap,
                    allow_birth=not missing_prefix,
                    sweep_query=self.liquidity.sweep_query if self.liquidity else None,
                )
            )
        return self.decisions[before:]
