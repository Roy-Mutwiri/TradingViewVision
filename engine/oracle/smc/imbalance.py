"""Pure three-closed-candle FVG geometry and wick-fill observations.

Original bounds are immutable. An unfilled remainder is a display projection,
not a resized historical zone. ATR is supplied explicitly by the shared ATR
primitive; this detector never computes or guesses a second ATR.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Annotated, Literal, Self, Sequence

from pydantic import Field, model_validator

from oracle.config import ZonesConfig
from oracle.indicators.ut_bot import ATRState, rma_atr
from oracle.models import Bar, Contract, Millis, Price, Text, Timeframe, Unit, timeframe_ms
from oracle.smc.zone_union import overlap_components, post_creation_bars


class FVGGeometry(Contract):
    schema_version: Literal[3] = 3
    symbol: Literal["XAUUSD"]
    tf: Timeframe
    direction: Literal["BULLISH", "BEARISH"]
    price_lo: Price
    price_hi: Price
    ce: Price
    size: Price
    atr_at_creation: Price
    fvg_min_atr: Annotated[float, Field(ge=0)]
    created_ms: Millis
    t_start_ms: Millis
    created_idx: Annotated[int, Field(ge=2)]
    source_bars: tuple[int, ...]
    source_object_ids: tuple[Text, ...]
    constituent_ids: tuple[Text, ...] = ()
    gap_adjacent: bool

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.price_hi <= self.price_lo:
            raise ValueError("FVG requires a positive gap")
        if self.ce != (self.price_hi + self.price_lo) / 2 or self.size != self.price_hi - self.price_lo:
            raise ValueError("FVG derived geometry does not match its bounds")
        if self.size < self.fvg_min_atr * self.atr_at_creation:
            raise ValueError("FVG is below its configured ATR gate")
        if not self.constituent_ids and self.source_bars != (self.created_idx - 2, self.created_idx - 1, self.created_idx):
            raise ValueError("FVG requires three consecutive candle indices")
        if len(self.source_bars) != len(self.source_object_ids):
            raise ValueError("FVG source bar indices must match source IDs")
        if self.constituent_ids and (len(self.constituent_ids) < 2
                                    or tuple(sorted(set(self.constituent_ids))) != self.constituent_ids):
            raise ValueError("union requires sorted unique constituent IDs")
        if self.t_start_ms > self.created_ms:
            raise ValueError("FVG drawing start cannot follow confirmation")
        return self

    @property
    def id(self) -> str:
        return hashlib.blake2b(self.canonical_json().encode(), digest_size=8).hexdigest()


class FillObservation(Contract):
    geometry_id: Text
    fill_pct: Unit
    unfilled: tuple[float, float] | None
    touched: bool
    fully_filled: bool
    body_beyond_far_edge: bool
    ce_status: Literal["RESPECTED", "WEAKENED", "OUTSIDE", "UNTESTED", "PROVISIONAL"]
    inversion_confirmed: bool
    source_bar_idx: Annotated[int, Field(ge=0)]
    source_object_id: Text
    confirmed: bool
    gap_direction: Literal["BULLISH", "BEARISH"]

    @property
    def inversion_direction(self) -> Literal["BULLISH", "BEARISH"] | None:
        if not self.inversion_confirmed:
            return None
        return "BEARISH" if self.gap_direction == "BULLISH" else "BULLISH"


def detect_fvg(
    bars: Sequence[Bar], *, atr: float | None, start_idx: int = 0,
    config: ZonesConfig | None = None,
) -> FVGGeometry | None:
    """Supply c1/c2/c3 and shared Wilder ATR(14) on this TF at c3 close."""
    if len(bars) != 3:
        raise ValueError("detect_fvg requires exactly three candles")
    if start_idx < 0:
        raise ValueError("start_idx must be nonnegative")
    c1, c2, c3 = bars
    if any(b.tf != c1.tf or b.symbol != c1.symbol or b.digits != c1.digits for b in bars):
        raise ValueError("FVG candles must have one symbol, timeframe and precision")
    if not c1.t_open_ms < c2.t_open_ms < c3.t_open_ms:
        raise ValueError("FVG candles must be ordered and unique")
    if not all(b.complete for b in bars) or atr is None:
        return None
    if not math.isfinite(atr) or atr <= 0:
        raise ValueError("ATR must be finite and positive")
    settings = config or ZonesConfig()
    if c3.l > c1.h:
        direction: Literal["BULLISH", "BEARISH"] = "BULLISH"
        lo, hi = c1.h, c3.l
    elif c3.h < c1.l:
        direction = "BEARISH"
        lo, hi = c3.h, c1.l
    else:
        return None
    size = hi - lo
    if size < settings.fvg_min_atr * atr:
        return None
    duration = timeframe_ms(c1.tf)
    return FVGGeometry(
        symbol=c1.symbol, tf=c1.tf, direction=direction, price_lo=lo, price_hi=hi,
        ce=(hi + lo) / 2, size=size, atr_at_creation=atr, fvg_min_atr=settings.fvg_min_atr,
        created_ms=c3.t_open_ms + duration, t_start_ms=c1.t_open_ms, created_idx=start_idx + 2,
        source_bars=(start_idx, start_idx + 1, start_idx + 2),
        source_object_ids=(c1.id, c2.id, c3.id),
        gap_adjacent=any(b.t_open_ms-a.t_open_ms>duration for a,b in zip(bars,bars[1:])),
    )


def observe_fill(
    gap: FVGGeometry, bar: Bar, *, bar_idx: int, previous_fill: float = 0,
) -> FillObservation:
    """Closed bodies decide CE/inversion; forming wicks give a provisional fill only.

    A bar gapping entirely past the gap is not traded coverage. It can invalidate
    by its close, but cannot create an IFVG without full wick coverage. Creation
    candles are rejected so the gap never consumes its own c3 boundary touch.
    """
    if bar.tf != gap.tf or bar.symbol != gap.symbol:
        raise ValueError("fill observation must use the gap's timeframe and symbol")
    if bar_idx <= gap.created_idx or bar.t_open_ms < gap.created_ms:
        raise ValueError("fill observation must follow gap creation")
    if not math.isfinite(previous_fill) or not 0 <= previous_fill <= 1:
        raise ValueError("previous_fill must be a fraction in [0, 1]")
    touched = bar.l <= gap.price_hi and bar.h >= gap.price_lo
    fill = previous_fill
    if touched:
        depth = (gap.price_hi-bar.l) if gap.direction == "BULLISH" else (bar.h-gap.price_lo)
        fill = max(fill, min(1.0, max(0.0, depth/gap.size)))
    full = fill == 1
    unfilled = None if full else (
        (gap.price_lo, gap.price_hi-fill*gap.size) if gap.direction == "BULLISH"
        else (gap.price_lo+fill*gap.size, gap.price_hi)
    )
    beyond = bar.complete and (bar.c < gap.price_lo if gap.direction == "BULLISH" else bar.c > gap.price_hi)
    weak = bar.c < gap.ce if gap.direction == "BULLISH" else bar.c > gap.ce
    inside = gap.price_lo <= bar.c <= gap.price_hi
    status: Literal["RESPECTED", "WEAKENED", "OUTSIDE", "UNTESTED", "PROVISIONAL"]
    if not bar.complete:
        status = "PROVISIONAL"
    elif weak:
        status = "WEAKENED"
    elif touched and inside:
        status = "RESPECTED"
    else:
        status = "OUTSIDE" if touched else "UNTESTED"
    return FillObservation(
        geometry_id=gap.id, fill_pct=fill, unfilled=unfilled, touched=touched,
        fully_filled=full, body_beyond_far_edge=beyond, ce_status=status,
        inversion_confirmed=beyond and full, source_bar_idx=bar_idx,
        source_object_id=bar.id, confirmed=bar.complete,
        gap_direction=gap.direction,
    )


class FVGRecord(Contract):
    """Immutable lifecycle snapshot; identity excludes advancing state/fill.

    Original geometry and its creation ATR survive every state transition.
    Restore the snapshot (including CE latch) when replay starts mid-history.
    """

    schema_version: Literal[4] = 4
    fidelity: Literal["TICK", "M1", "BAR"] = "BAR"
    geometry: FVGGeometry
    kind: Literal["FVG", "IFVG"] = "FVG"
    parent_id: Text | None = None
    inversion_depth: Literal[0, 1] = 0
    born_ms: Millis
    born_bar_index: Annotated[int, Field(ge=2)]
    reason_chain: tuple[str, ...] = ()
    state: Literal["FRESH", "TOUCHED", "MITIGATED", "FILLED", "INVERTED", "INVALID", "MERGED"] = "FRESH"
    fill_pct: Unit = 0
    weakened: bool = False
    weakened_at_ms: Millis | None = None
    weakened_bar_index: Annotated[int, Field(ge=0)] | None = None
    ce_lost: bool = False
    ce_lost_at_ms: Millis | None = None
    ce_lost_bar_index: Annotated[int, Field(ge=0)] | None = None
    last_bar_index: Annotated[int, Field(ge=2)]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.kind == "IFVG") != (self.inversion_depth == 1 and self.parent_id is not None):
            raise ValueError("IFVG requires depth 1 and a parent link")
        if self.kind == "FVG" and (self.parent_id is not None or self.inversion_depth != 0):
            raise ValueError("original FVG cannot have an inversion parent")
        if self.weakened != (self.weakened_at_ms is not None and self.weakened_bar_index is not None):
            raise ValueError("CE weakening requires its first confirmed bar provenance")
        if self.ce_lost != (self.ce_lost_at_ms is not None and self.ce_lost_bar_index is not None):
            raise ValueError("union CE loss requires its first confirmed bar provenance")
        return self

    @property
    def id(self) -> str:
        if self.geometry.constituent_ids and self.kind == "FVG":
            return hashlib.blake2b(json.dumps(self.geometry.constituent_ids, separators=(",", ":")).encode(),
                                   digest_size=8).hexdigest()
        terms = (self.geometry.id, self.kind, self.parent_id, self.inversion_depth,
                 self.born_ms, self.born_bar_index)
        return hashlib.blake2b(repr(terms).encode(), digest_size=8).hexdigest()

    @property
    def is_target(self) -> bool:
        return self.state not in ("INVERTED", "INVALID", "MERGED") and self.fill_pct < 1

    @property
    def eligible_for_a_setup(self) -> bool:
        return self.kind == "FVG" and self.is_target and not self.weakened and not self.ce_lost

    @property
    def renders(self) -> bool:
        return self.state not in ("INVERTED", "INVALID", "MERGED")

    @property
    def constituent_ids(self) -> tuple[str, ...]:
        return self.geometry.constituent_ids

    @property
    def strength(self) -> int:
        return len(self.constituent_ids) if self.constituent_ids else 1


class FVGEvent(Contract):
    kind: Literal["CE_LOST", "INVERTED", "INVALID", "REINVERSION_ATTEMPT", "MERGED", "MERGE_REJECTED"]
    zone_id: Text
    bar_index: Annotated[int, Field(ge=0)]
    bar_id: Text
    at_ms: Millis
    reason: Text


class FVGTransition(Contract):
    record: FVGRecord
    child: FVGRecord | None = None
    events: tuple[FVGEvent, ...] = ()


def create_fvg_record(geometry: FVGGeometry) -> FVGRecord:
    return FVGRecord(geometry=geometry, born_ms=geometry.created_ms,
                     born_bar_index=geometry.created_idx, last_bar_index=geometry.created_idx)


class FVGMergePlan(Contract):
    """Whole connected components, before any immutable union is committed."""

    components: tuple[tuple[FVGRecord, ...], ...]
    events: tuple[FVGEvent, ...] = ()


class FVGMergeResult(Contract):
    records: tuple[FVGRecord, ...]
    events: tuple[FVGEvent, ...] = ()


def plan_fvg_merges(records: Sequence[FVGRecord], *, config: ZonesConfig | None = None) -> FVGMergePlan:
    """Intersection / smaller, strict threshold, fixed traversal, all-or-nothing span cap."""
    settings = config or ZonesConfig()
    # FILLED gaps are terminal for merging: they have no unfilled zone left to
    # combine, and retaining them in the overlap graph makes long replays
    # quadratic without changing any visible or tradeable union.
    candidates = sorted((r for r in records if r.kind == "FVG"
                         and r.state in ("FRESH", "TOUCHED", "MITIGATED")),
                        key=lambda r: (r.geometry.t_start_ms, r.geometry.price_lo, r.id))
    if len({r.id for r in candidates}) != len(candidates):
        raise ValueError("merge candidates must have unique IDs")
    components = overlap_components(
        [(r.geometry.price_lo,r.geometry.price_hi) for r in candidates],
        [(r.geometry.symbol,r.geometry.tf,r.geometry.direction,r.state) for r in candidates],
        settings.fvg_merge_overlap,
    )
    accepted: list[tuple[FVGRecord, ...]] = []
    events: list[FVGEvent] = []
    for indices in components:
        group = [candidates[i] for i in indices]
        if len(group) < 2:
            continue
        latest = max(group, key=lambda r: (r.geometry.created_ms, r.id))
        lo = min(r.geometry.price_lo for r in group)
        hi = max(r.geometry.price_hi for r in group)
        if hi-lo > settings.max_merged_span_atr * latest.geometry.atr_at_creation:
            ids = sorted(r.id for r in group)
            events.append(FVGEvent(kind="MERGE_REJECTED", zone_id=latest.id,
                                   at_ms=latest.geometry.created_ms,
                                   bar_index=latest.geometry.created_idx,
                                   bar_id=latest.geometry.source_object_ids[-1],
                                   reason=f"span {hi-lo} exceeds frozen {settings.max_merged_span_atr} ATR; constituents {ids}"))
            continue
        accepted.append(tuple(group))
    return FVGMergePlan(components=tuple(accepted), events=tuple(events))


def build_fvg_union(component: Sequence[FVGRecord], *, config: ZonesConfig | None = None) -> FVGRecord:
    """Freeze geometry and inherited CE provenance; fill is replayed before commit."""
    if len(component) < 2:
        raise ValueError("union requires at least two constituents")
    ordered = sorted(component, key=lambda r: (r.geometry.t_start_ms, r.geometry.price_lo, r.id))
    first = ordered[0]
    if any((r.kind, r.geometry.symbol, r.geometry.tf, r.geometry.direction, r.state) != (
            first.kind, first.geometry.symbol, first.geometry.tf, first.geometry.direction, first.state)
           or not r.renders or r.kind != "FVG" for r in ordered):
        raise ValueError("union constituents must match direction, timeframe and live state")
    latest = max(ordered, key=lambda r: (r.geometry.created_ms, r.id))
    ids = tuple(sorted({leaf for r in ordered for leaf in (r.constituent_ids or (r.id,))}))
    lo = min(r.geometry.price_lo for r in ordered)
    hi = max(r.geometry.price_hi for r in ordered)
    settings = config or ZonesConfig()
    if hi-lo > settings.max_merged_span_atr * latest.geometry.atr_at_creation:
        raise ValueError("union exceeds frozen ATR span cap")
    sources = sorted({pair for r in ordered for pair in zip(r.geometry.source_bars, r.geometry.source_object_ids)})
    geometry = FVGGeometry.model_validate(latest.geometry.model_dump() | {
        "price_lo": lo, "price_hi": hi, "ce": (lo+hi)/2, "size": hi-lo,
        "t_start_ms": min(r.geometry.t_start_ms for r in ordered),
        "constituent_ids": ids, "source_bars": tuple(index for index, _ in sources),
        "source_object_ids": tuple(object_id for _, object_id in sources),
        "gap_adjacent": any(r.geometry.gap_adjacent for r in ordered),
    })
    losses = [(r.weakened_at_ms, r.weakened_bar_index) for r in ordered if r.weakened]
    # A prior union's own CE loss is a historical loss in the next union as well.
    losses.extend((r.ce_lost_at_ms, r.ce_lost_bar_index) for r in ordered if r.ce_lost)
    earliest_loss = min(losses) if losses else (None, None)
    return FVGRecord(geometry=geometry, born_ms=geometry.created_ms,
                     born_bar_index=geometry.created_idx, last_bar_index=geometry.created_idx,
                     state=first.state, weakened=bool(losses), weakened_at_ms=earliest_loss[0],
                     weakened_bar_index=earliest_loss[1])


def merge_fvgs(
    records: Sequence[FVGRecord], bars: Sequence[Bar], *, as_of_ms: int,
    config: ZonesConfig | None = None,
) -> FVGMergeResult:
    """Commit graph unions at detection; keep terminal constituents in history.

    Fill walks stored closed bars from created_ms, excluding formation candles.
    t_start_ms is a drawing anchor only. No future or forming bars contribute.
    Union CE is tracked separately, only after the union's confirmation horizon.
    """
    bars = tuple(bar for bar in bars if bar.t_open_ms+timeframe_ms(bar.tf) <= as_of_ms)
    if any(not bar.complete for bar in bars):
        raise ValueError("union history must contain confirmed bars only")
    if any(a.t_open_ms >= b.t_open_ms for a, b in zip(bars, bars[1:])):
        raise ValueError("union history must be ordered and unique")
    plan = plan_fvg_merges(records, config=config)
    updated = {r.id: r for r in records}
    if len(updated) != len(records):
        raise ValueError("FVG history must have unique IDs")
    events = list(plan.events)
    for component in plan.components:
        union = build_fvg_union(component, config=config)
        geometry = union.geometry
        if geometry.created_ms > as_of_ms:
            raise ValueError("union cannot precede its latest constituent confirmation")
        if any(bar.tf != geometry.tf or bar.symbol != geometry.symbol for bar in bars):
            raise ValueError("union history must use its timeframe and symbol")
        by_time = {bar.t_open_ms: bar for bar in bars}
        if geometry.t_start_ms not in by_time or geometry.created_ms-timeframe_ms(geometry.tf) not in by_time:
            raise ValueError("union history must cover drawing start and latest c3")
        # Replay union-specific CE and lifecycle only from its own creation.
        absolute_index = geometry.created_idx
        for bar in post_creation_bars(bars, geometry.created_ms):
            # Source indices are absolute, not positions in a sliced history.
            absolute_index += 1
            transition = advance_fvg(union, bar, bar_idx=absolute_index)
            union = transition.record
            events.extend(transition.events)
            if transition.child is not None:
                updated[transition.child.id] = transition.child
        for constituent in component:
            updated[constituent.id] = FVGRecord.model_validate(constituent.model_dump() | {"state": "MERGED"})
        updated[union.id] = union
        events.append(FVGEvent(kind="MERGED", zone_id=union.id, bar_index=geometry.created_idx,
                               bar_id=by_time[geometry.created_ms-timeframe_ms(geometry.tf)].id,
                               at_ms=geometry.created_ms,
                               reason=f"union of {union.constituent_ids}"))
    return FVGMergeResult(records=tuple(sorted(updated.values(), key=lambda r: (
        r.geometry.t_start_ms, r.geometry.price_lo, r.id))), events=tuple(events))


def advance_fvg(record: FVGRecord, bar: Bar, *, bar_idx: int) -> FVGTransition:
    """Only confirmed bars advance the record. Terminal/replayed bars are idempotent."""
    if record.state in ("INVERTED", "INVALID", "MERGED"):
        return FVGTransition(record=record)
    if not bar.complete:
        raise ValueError("forming bars cannot advance the canonical FVG lifecycle")
    if bar_idx <= record.last_bar_index:
        return FVGTransition(record=record)
    # A gap can only fill, lose CE, or invert when price reaches its near edge.
    # Avoid rebuilding an immutable record for unrelated bars; the next touching
    # bar still carries its absolute index, so lifecycle and provenance are unchanged.
    if (
        record.geometry.direction == "BULLISH" and bar.l > record.geometry.price_hi
    ) or (
        record.geometry.direction == "BEARISH" and bar.h < record.geometry.price_lo
    ):
        return FVGTransition(record=record)
    observation = observe_fill(record.geometry, bar, bar_idx=bar_idx, previous_fill=record.fill_pct)
    at_ms = bar.t_open_ms + timeframe_ms(bar.tf)
    events: list[FVGEvent] = []
    updates: dict[str, object] = {"fill_pct": observation.fill_pct, "last_bar_index": bar_idx}
    is_union = bool(record.constituent_ids)
    already_lost = record.ce_lost if is_union else record.weakened
    if observation.ce_status == "WEAKENED" and not already_lost:
        if is_union:
            updates.update(ce_lost=True, ce_lost_at_ms=at_ms, ce_lost_bar_index=bar_idx)
        else:
            updates.update(weakened=True, weakened_at_ms=at_ms, weakened_bar_index=bar_idx)
        events.append(FVGEvent(kind="CE_LOST", zone_id=record.id, bar_index=bar_idx,
                               bar_id=bar.id, at_ms=at_ms, reason="body close through CE"))
    child = None
    if observation.body_beyond_far_edge:
        if record.kind == "FVG" and observation.inversion_confirmed:
            updates["state"] = "INVERTED"
            direction = observation.inversion_direction
            assert direction is not None
            geometry = FVGGeometry.model_validate(record.geometry.model_dump() | {"direction": direction})
            reason = f"inverted from FVG {record.id} on body close at {bar.c}"
            child = FVGRecord(geometry=geometry, kind="IFVG", parent_id=record.id,
                              inversion_depth=1, born_ms=at_ms, born_bar_index=bar_idx,
                              last_bar_index=bar_idx, reason_chain=(reason,))
            events.append(FVGEvent(kind="INVERTED", zone_id=record.id, bar_index=bar_idx,
                                   bar_id=bar.id, at_ms=at_ms, reason=reason))
        else:
            updates["state"] = "INVALID"
            kind: Literal["INVALID", "REINVERSION_ATTEMPT"] = (
                "REINVERSION_ATTEMPT" if record.kind == "IFVG" else "INVALID")
            events.append(FVGEvent(kind=kind, zone_id=record.id, bar_index=bar_idx,
                                   bar_id=bar.id, at_ms=at_ms,
                                   reason="IFVG depth cap reached" if record.kind == "IFVG"
                                   else "far-edge close without full traded coverage"))
    elif observation.fully_filled:
        updates["state"] = "FILLED"
    elif observation.touched:
        updates["state"] = "TOUCHED"
    updated = FVGRecord.model_validate(record.model_dump() | updates)
    return FVGTransition(record=updated, child=child, events=tuple(events))


@dataclass(frozen=True)
class ImbalanceCursor:
    """Checkpointable pure incremental detector: one ATR implementation, closed TF bars only."""

    config: ZonesConfig = ZonesConfig()
    atr_state: ATRState = ATRState(14)
    recent: tuple[Bar, ...] = ()
    records: tuple[FVGRecord, ...] = ()
    events: tuple[FVGEvent, ...] = ()
    next_index: int = 0
    stored_bars: tuple[Bar, ...] = ()


def advance_imbalance(cursor: ImbalanceCursor, bar: Bar) -> ImbalanceCursor:
    if not bar.complete:
        raise ValueError("imbalance cursor accepts confirmed bars only")
    if cursor.recent and (bar.tf != cursor.recent[-1].tf or bar.symbol != cursor.recent[-1].symbol
                          or bar.t_open_ms <= cursor.recent[-1].t_open_ms):
        raise ValueError("cursor requires one timeframe, symbol and increasing timestamps")
    index = cursor.next_index
    atr_values, atr_state = rma_atr([bar], 14, state=cursor.atr_state, with_state=True)
    records: list[FVGRecord] = []
    events = list(cursor.events)
    for record in cursor.records:
        result = advance_fvg(record, bar, bar_idx=index)
        records.append(result.record)
        if result.child is not None:
            records.append(result.child)
        events.extend(result.events)
    recent = (*cursor.recent[-2:], bar)
    stored_bars = (*cursor.stored_bars, bar)
    if len(recent) == 3:
        geometry = detect_fvg(recent, atr=atr_values[-1], start_idx=index-2, config=cursor.config)
        if geometry is not None:
            records.append(create_fvg_record(geometry))
            merged = merge_fvgs(records, stored_bars, as_of_ms=bar.t_open_ms+timeframe_ms(bar.tf),
                                config=cursor.config)
            records = list(merged.records)
            events.extend(event for event in merged.events if event not in events)
    return ImbalanceCursor(cursor.config, atr_state, recent, tuple(records), tuple(events), index+1, stored_bars)
