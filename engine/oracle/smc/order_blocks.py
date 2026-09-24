"""Causal OB validator. Frozen boundaries; explicit EvalPoints alone drive state.

Origin clusters use configured body_to_wick/body_only/full_range boundaries.
Candidate legs await a real same-timeframe structure event, never a fake break.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Literal, cast, overload

from oracle.candidates.contracts import Decision, EvalPoint
from oracle.config import StructureConfig, ZonesConfig
from oracle.indicators.ut_bot import ATRState, rma_atr
from oracle.models import Bar, timeframe_ms
from oracle.smc.imbalance import FVGGeometry, ImbalanceCursor, advance_imbalance
from oracle.smc.ob_contracts import OBCandidate, OBGeometry, OBRecord
from oracle.smc.structure import (
    StructureCursor,
    StructureEvent,
    SweepQuery,
    advance_structure,
    no_sweep,
)
from oracle.smc.swings import SwingConfig
from oracle.smc.zone_union import overlap_components, post_creation_bars


def content_id(value: object) -> str:
    return hashlib.blake2b(json.dumps(value, sort_keys=True).encode(), digest_size=8).hexdigest()


class _BarsWithTail(Sequence[Bar]):
    """Zero-copy sequence view of confirmed history followed by the evaluated bar."""

    def __init__(self, closed: Sequence[Bar], tail: Bar) -> None:
        self.closed = closed
        self.tail = tail

    def __len__(self) -> int:
        return len(self.closed) + 1

    @overload
    def __getitem__(self, index: int) -> Bar: ...

    @overload
    def __getitem__(self, index: slice) -> list[Bar]: ...

    def __getitem__(self, index: int | slice) -> Bar | list[Bar]:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return [self[i] for i in range(start, stop, step)]
        normalized = index if index >= 0 else len(self) + index
        if not 0 <= normalized < len(self):
            raise IndexError(index)
        return self.tail if normalized == len(self.closed) else self.closed[normalized]


def origin_bounds(bars: Sequence[Bar], direction: str, boundary: str) -> tuple[float, float]:
    if boundary == "full_range":
        return min(b.l for b in bars), max(b.h for b in bars)
    if boundary == "body_only":
        return min(min(b.o, b.c) for b in bars), max(max(b.o, b.c) for b in bars)
    if direction == "BULLISH":
        return min(b.l for b in bars), max(max(b.o, b.c) for b in bars)
    return min(min(b.o, b.c) for b in bars), max(b.h for b in bars)


def advance_ob(
    r: OBRecord, p: EvalPoint, b: Bar, cfg: ZonesConfig, at: int, bar_idx: int | None = None
) -> tuple[OBRecord, OBRecord | None]:
    g = r.geometry
    if r.state in ("INVALID", "MERGED") or p.seq <= r.last_seq or b.t_open_ms < g.created_ms:
        return r, None
    beyond = b.c < g.price_lo if g.direction == "BULLISH" else b.c > g.price_hi
    if p.bar_phase == "CLOSE" and beyond:
        terminal = r.model_copy(update=dict(state="INVALID", last_seq=p.seq))
        if r.inversion_depth:
            return terminal, None
        flipped = g.model_copy(
            update=dict(
                direction="BEARISH" if g.direction == "BULLISH" else "BULLISH",
                created_ms=at,
                created_idx=p.bar_index if bar_idx is None else bar_idx,
                constituent_ids=(),
                source_bars=(*g.source_bars, p.bar_index if bar_idx is None else bar_idx),
                source_object_ids=(*g.source_object_ids, b.id),
            )
        )
        return terminal, OBRecord(
            geometry=flipped,
            state="BREAKER",
            validated_by_event_id=r.validated_by_event_id,
            validation_event_ids=r.validation_event_ids,
            validation_kind=r.validation_kind,
            parent_id=r.id,
            inversion_depth=1,
            last_seq=p.seq,
        )
    touch = b.l <= g.price_hi and b.h >= g.price_lo
    mitigate = (
        b.l <= g.ce <= b.h
        if cfg.ob_mitigation == "wick_50"
        else p.bar_phase == "CLOSE"
        and (
            g.price_lo <= b.c <= g.price_hi
            if cfg.ob_mitigation == "body_inside"
            else touch and beyond
        )
    )
    if not touch or r.state in ("MITIGATED", "BREAKER"):
        return r, None
    update: dict[str, object] = dict(last_seq=p.seq)
    if r.state not in ("MITIGATED", "BREAKER"):
        if mitigate:
            update.update(state="MITIGATED", mitigated_ms=at, mitigated_bar_open_ms=b.t_open_ms)
        elif touch:
            update["state"] = "TOUCHED"
    return r.model_copy(update=update), None


def merge_order_blocks(
    records: Sequence[OBRecord], bars: Sequence[Bar], cfg: ZonesConfig
) -> tuple[tuple[OBRecord, ...], tuple[dict[str, object], ...]]:
    live = sorted(
        (r for r in records if r.state in ("FRESH", "TOUCHED", "MITIGATED")),
        key=lambda r: (r.geometry.t_start_ms, r.geometry.price_lo, r.id),
    )
    groups = overlap_components(
        [(r.geometry.price_lo, r.geometry.price_hi) for r in live],
        [(r.geometry.tf, r.geometry.direction, r.state) for r in live],
        cfg.ob_merge_overlap,
    )
    result = {r.id: r for r in records}
    rejects: list[dict[str, object]] = []
    for indices in groups:
        if len(indices) < 2:
            continue
        group = [live[i] for i in indices]
        latest = max(group, key=lambda r: (r.geometry.created_ms, r.id))
        lo = min(r.geometry.price_lo for r in group)
        hi = max(r.geometry.price_hi for r in group)
        if hi - lo > cfg.max_merged_span_atr * latest.geometry.atr_at_creation:
            rejects.append(dict(reason="SPAN_CAP", constituent_ids=sorted(r.id for r in group)))
            continue
        ids = tuple(
            sorted({leaf for r in group for leaf in (r.geometry.constituent_ids or (r.id,))})
        )
        sources = sorted(
            {
                pair
                for r in group
                for pair in zip(r.geometry.source_bars, r.geometry.source_object_ids, strict=True)
            }
        )
        g = latest.geometry.model_copy(
            update=dict(
                price_lo=lo,
                price_hi=hi,
                ce=(lo + hi) / 2,
                size=hi - lo,
                t_start_ms=min(r.geometry.t_start_ms for r in group),
                constituent_ids=ids,
                source_bars=tuple(i for i, _ in sources),
                source_object_ids=tuple(oid for _, oid in sources),
            )
        )
        union = OBRecord(
            geometry=g,
            state=latest.state,
            validated_by_event_id=latest.validated_by_event_id,
            validation_kind="CHoCH" if any(r.validation_kind == "CHoCH" for r in group) else "BOS",
            validation_event_ids=tuple(
                sorted(
                    {
                        eid
                        for r in group
                        for eid in (r.validation_event_ids or (r.validated_by_event_id,))
                    }
                )
            ),
            mitigated_ms=min(
                (r.mitigated_ms for r in group if r.mitigated_ms is not None), default=None
            ),
            mitigated_bar_open_ms=min(
                (r.mitigated_bar_open_ms for r in group if r.mitigated_bar_open_ms is not None),
                default=None,
            ),
        )
        for i, b in enumerate(post_creation_bars(bars, g.created_ms)):
            p = EvalPoint(
                seq=i,
                t_broker_ms=b.t_open_ms + timeframe_ms(b.tf),
                price=b.c,
                bar_index=g.created_idx + i + 1,
                bar_phase="CLOSE",
                source="BAR_COARSE",
                fidelity="BAR",
            )
            union, child = advance_ob(union, p, b, cfg, p.t_broker_ms)
            if child:
                result[child.id] = child
        for r in group:
            result[r.id] = r.model_copy(update={"state": "MERGED"})
        result[union.id] = union
    return tuple(sorted(result.values(), key=lambda r: (r.geometry.created_ms, r.id))), tuple(
        rejects
    )


class OrderBlockEngine:
    def __init__(
        self,
        config: ZonesConfig,
        structure_config: StructureConfig = StructureConfig(),
        swing_config: SwingConfig | None = None,
    ) -> None:
        self.config = config
        self.structure_config = structure_config
        self.swing_config = swing_config
        self.structure: StructureCursor | None = None
        self.candidates: dict[str, OBCandidate] = {}
        self.records: tuple[OBRecord, ...] = ()
        self.live_records: dict[str, OBRecord] = {}
        self.decisions: list[Decision] = []
        self.rejections: list[dict[str, object]] = []
        self.rejection_keys: set[tuple[int, str, str]] = set()
        self.used: set[tuple[int, str]] = set()

    def emit(
        self,
        p: EvalPoint,
        c: OBCandidate,
        action: str,
        at: int,
        reason: str | None = None,
        criterion: str | None = None,
        confirmed_id: str | None = None,
    ) -> None:
        g = c.geometry
        d = Decision.model_validate(
            dict(
                seq=p.seq,
                t_broker_ms=p.t_broker_ms,
                object_id=c.id,
                kind="OB",
                action=action,
                reason=reason,
                criterion=criterion,
                confirmed_id=confirmed_id,
                fidelity=p.fidelity,
                tf=g.tf,
                t_utc_ms=at,
                geometry=g,
                source_bars=g.source_bars,
                source_object_ids=g.source_object_ids,
            )
        )
        self.decisions.append(d)
        self.candidates[c.id] = c.model_copy(
            update=dict(
                state="PROMOTED"
                if action == "PROMOTE"
                else "DISCARDED"
                if action == "DISCARD"
                else "CANDIDATE",
                reason=reason,
                criterion=criterion,
                decision_id=d.id,
            )
        )

    def reject(self, p: EvalPoint, direction: str, criterion: str, at: int, tf: str) -> None:
        key = (p.bar_index, direction, criterion)
        if key in self.rejection_keys:
            return
        self.rejection_keys.add(key)
        self.rejections.append(
            dict(
                id=content_id((tf, *key)),
                seq=p.seq,
                t_broker_ms=p.t_broker_ms,
                t_utc_ms=at,
                timeframe=tf,
                action="REJECT",
                reason="FAILED_CRITERIA",
                criterion=criterion,
                direction=direction,
                detail="NO_ORIGIN" if criterion == "ORIGIN" else criterion,
            )
        )

    def process(
        self,
        p: EvalPoint,
        closed: Sequence[Bar],
        bar: Bar,
        atr: float | None,
        fvgs: Sequence[FVGGeometry],
        *,
        at_ms: int,
        data_gap: bool = False,
        allow_birth: bool = True,
        sweep_query: SweepQuery | None = None,
    ) -> list[Decision]:
        before = len(self.decisions)
        idx = len(closed)
        bars = _BarsWithTail(closed, bar)
        cfg = self.config
        events: tuple[StructureEvent, ...] = ()
        if p.bar_phase == "CLOSE" and not data_gap:
            prior = len(self.structure.events) if self.structure else 0
            self.structure = advance_structure(
                self.structure, bar, self.structure_config, swing_config=self.swing_config,
                sweep_query=sweep_query or no_sweep,
            )
            assert self.structure is not None
            events = self.structure.events[prior:]
        changed_records: dict[str, OBRecord] = {}
        added_records: list[OBRecord] = []
        merge_dirty = False
        for r in tuple(self.live_records.values()):
            if p.bar_phase != "CLOSE" and r.state in ("MITIGATED", "BREAKER"):
                continue
            updated, child = advance_ob(r, p, bar, cfg, at_ms, bar_idx=idx)
            if updated != r or child is not None:
                merge_dirty = True
                changed_records[r.id] = updated
                if child:
                    added_records.append(child)
            if updated.state in ("INVALID", "MERGED"):
                self.live_records.pop(r.id, None)
            else:
                self.live_records[r.id] = updated
            if child is not None and child.state not in ("INVALID", "MERGED"):
                self.live_records[child.id] = child
            if updated.state != r.state:
                g = r.geometry
                self.decisions.append(
                    Decision.model_validate(
                        dict(
                            seq=p.seq,
                            t_broker_ms=p.t_broker_ms,
                            object_id=r.id,
                            kind="OB",
                            action="UPDATE",
                            fidelity=p.fidelity,
                            tf=g.tf,
                            t_utc_ms=at_ms,
                            criterion=updated.state,
                            confirmed_id=child.id if child else r.id,
                            geometry=g,
                            source_bars=g.source_bars,
                            source_object_ids=g.source_object_ids,
                        )
                    )
                )
        if changed_records or added_records:
            self.records = tuple(changed_records.get(r.id, r) for r in self.records) + tuple(
                added_records
            )
        for c in tuple(self.candidates.values()):
            if c.state != "CANDIDATE":
                continue
            g = c.geometry
            direction = "UP" if g.direction == "BULLISH" else "DOWN"
            valid = next(
                (
                    e
                    for e in events
                    if e.direction == direction
                    and e.timeframe == g.tf
                    and g.origin_idx < e.break_bar_idx <= g.origin_idx + cfg.ob_max_leg_bars
                ),
                None,
            )
            if data_gap:
                self.emit(p, c, "DISCARD", at_ms, "DATA_GAP")
                continue
            if any(e.direction != direction for e in events):
                self.emit(p, c, "DISCARD", at_ms, "INVALIDATED", "STRUCTURE")
                continue
            if valid:
                leg = bars[g.leg_start_idx :]
                ratio = (max(b.h for b in leg) - min(b.l for b in leg)) / (atr or g.atr_at_creation)
                gaps = [
                    f
                    for f in fvgs
                    if f.direction == g.direction and g.leg_start_idx + 1 <= f.created_idx <= idx
                ]
                failed = (
                    "DISPLACEMENT"
                    if ratio < cfg.ob_displacement_atr
                    else "IMBALANCE"
                    if not gaps
                    else None
                )
                if failed:
                    self.emit(p, c, "DISCARD", at_ms, "FAILED_CRITERIA", failed)
                    continue
                geom = g.model_copy(
                    update=dict(
                        created_ms=at_ms,
                        created_idx=idx,
                        atr_at_creation=atr or g.atr_at_creation,
                        displacement_atr=ratio,
                        fvg_ids=tuple(sorted(f.id for f in gaps)),
                        source_bars=tuple(range(min(g.source_bars), idx + 1)),
                        source_object_ids=tuple(b.id for b in bars[min(g.source_bars) : idx + 1]),
                    )
                )
                record = OBRecord(
                    geometry=geom,
                    validated_by_event_id=valid.id,
                    validation_event_ids=(valid.id,),
                    validation_kind=valid.kind,
                    last_seq=p.seq,
                )
                self.records = (*self.records, record)
                self.live_records[record.id] = record
                merge_dirty = True
                self.used.add((g.origin_idx, g.direction))
                self.emit(
                    p,
                    c.model_copy(update={"geometry": geom}),
                    "PROMOTE",
                    at_ms,
                    confirmed_id=record.id,
                )
            elif idx >= g.origin_idx + cfg.ob_max_leg_bars:
                self.emit(p, c, "DISCARD", at_ms, "FAILED_CRITERIA", "STRUCTURE")
                self.used.add((g.origin_idx, g.direction))
                self.reject(p, g.direction, "STRUCTURE", at_ms, g.tf)
        if allow_birth and atr and not data_gap and len(bars) >= 3:
            for direction in ("BULLISH", "BEARISH"):

                def opposite(b: Bar) -> bool:
                    return b.c < b.o if direction == "BULLISH" else b.c > b.o

                origin = next(
                    (
                        i
                        for i in range(idx - 1, max(-1, idx - cfg.ob_max_leg_bars - 1), -1)
                        if opposite(bars[i])
                    ),
                    None,
                )
                if origin is None:
                    if p.bar_phase == "CLOSE":
                        self.reject(p, direction, "ORIGIN", at_ms, bar.tf)
                    continue
                if (origin, direction) in self.used or any(
                    c.geometry.origin_idx == origin
                    and c.geometry.direction == direction
                    and c.state == "CANDIDATE"
                    for c in self.candidates.values()
                ):
                    continue
                leg = bars[origin + 1 :]
                ratio = (max(b.h for b in leg) - min(b.l for b in leg)) / atr
                gaps = [
                    f
                    for f in fvgs
                    if f.direction == direction and origin + 2 <= f.created_idx <= idx
                ]
                failed = (
                    "DISPLACEMENT"
                    if ratio < cfg.ob_displacement_atr
                    else "IMBALANCE"
                    if not gaps
                    else None
                )
                if failed:
                    if p.bar_phase == "CLOSE":
                        self.reject(p, direction, failed, at_ms, bar.tf)
                    continue
                valid = next(
                    (
                        e
                        for e in events
                        if e.direction == ("UP" if direction == "BULLISH" else "DOWN")
                        and origin < e.break_bar_idx <= origin + cfg.ob_max_leg_bars
                    ),
                    None,
                )
                if not cfg.ob_candidate_on_displacement and valid is None:
                    continue
                start = origin
                while (
                    start > 0
                    and origin - start + 1 < cfg.ob_max_cluster
                    and opposite(bars[start - 1])
                ):
                    start -= 1
                lo, hi = origin_bounds(bars[start : origin + 1], direction, cfg.ob_boundary)
                if hi <= lo:
                    continue
                g = OBGeometry(
                    tf=bar.tf,
                    direction=cast(Literal["BULLISH", "BEARISH"], direction),
                    price_lo=lo,
                    price_hi=hi,
                    ce=(lo + hi) / 2,
                    size=hi - lo,
                    atr_at_creation=atr,
                    created_ms=at_ms,
                    t_start_ms=bars[start].t_open_ms,
                    created_idx=idx,
                    origin_idx=origin,
                    leg_start_idx=origin + 1,
                    boundary=cfg.ob_boundary,
                    displacement_atr=ratio,
                    source_bars=tuple(range(start, idx + 1)),
                    source_object_ids=tuple(b.id for b in bars[start : idx + 1]),
                    fvg_ids=tuple(sorted(f.id for f in gaps)),
                )
                c = OBCandidate(
                    id=content_id((bar.tf, direction, bars[origin].id, p.seq)),
                    geometry=g,
                    born_bar_index=idx,
                    fidelity=p.fidelity,
                )
                self.emit(p, c, "CREATE", at_ms)
                if valid:
                    record = OBRecord(
                        geometry=g,
                        validated_by_event_id=valid.id,
                        validation_event_ids=(valid.id,),
                        validation_kind=valid.kind,
                        last_seq=p.seq,
                    )
                    self.records = (*self.records, record)
                    self.live_records[record.id] = record
                    merge_dirty = True
                    self.used.add((origin, direction))
                    self.emit(p, c, "PROMOTE", at_ms, confirmed_id=record.id)
                elif p.bar_phase == "CLOSE" and idx >= origin + cfg.ob_max_leg_bars:
                    self.emit(p, c, "DISCARD", at_ms, "FAILED_CRITERIA", "STRUCTURE")
                    self.used.add((origin, direction))
                    self.reject(p, direction, "STRUCTURE", at_ms, bar.tf)
        if p.bar_phase == "CLOSE" and merge_dirty:
            prior_records = {r.id: r for r in self.records}
            self.records, rejects = merge_order_blocks(self.records, bars, cfg)
            self.live_records = {
                r.id: r for r in self.records if r.state not in ("INVALID", "MERGED")
            }
            self.rejections.extend(rejects)
            for r in self.records:
                if r.id not in prior_records and r.geometry.constituent_ids:
                    g = r.geometry
                    self.decisions.append(
                        Decision.model_validate(
                            dict(
                                seq=p.seq,
                                t_broker_ms=p.t_broker_ms,
                                object_id=r.id,
                                kind="OB",
                                action="UPDATE",
                                reason="MERGED",
                                fidelity=p.fidelity,
                                tf=g.tf,
                                t_utc_ms=at_ms,
                                criterion="CONFIRMED_UNION",
                                union_id=r.id,
                                geometry=g,
                                source_bars=g.source_bars,
                                source_object_ids=g.source_object_ids,
                            )
                        )
                    )
        return self.decisions[before:]


def order_blocks(
    bars: Sequence[Bar],
    config: ZonesConfig | None = None,
    structure_config: StructureConfig = StructureConfig(),
) -> OrderBlockEngine:
    settings = config or ZonesConfig()
    engine = OrderBlockEngine(settings, structure_config)
    imb = ImbalanceCursor(config=settings)
    closed: list[Bar] = []
    state = ATRState(14)
    for idx, b in enumerate(bars):
        if not b.complete:
            raise ValueError("order_blocks requires a confirmed prefix")
        values, state = rma_atr([b], 14, state=state, with_state=True)
        imb = advance_imbalance(imb, b)
        p = EvalPoint(
            seq=idx,
            t_broker_ms=b.t_open_ms + timeframe_ms(b.tf),
            price=b.c,
            bar_index=idx,
            bar_phase="CLOSE",
            source="BAR_COARSE",
            fidelity="BAR",
        )
        engine.process(
            p,
            closed,
            b,
            values[0],
            [r.geometry for r in imb.records if r.kind == "FVG"],
            at_ms=p.t_broker_ms,
        )
        closed.append(b)
    return engine
