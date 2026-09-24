"""Read-only thesis projection over existing structure, zones, pools and calls.

The thesis never creates, suppresses or edits calls. It is a display contract for
what the current engine state implies at this EvalPoint/paint point.
"""
from __future__ import annotations

from typing import Any, Literal

from oracle.analysis.contracts import Call
from oracle.models import Contract, DrawObject, content_hash
from oracle.smc.liquidity_contracts import Pool
from oracle.smc.structure import StructureState

Stage = Literal[
    "NO_BIAS", "WAITING_FOR_PRICE", "PRICE_AT_ZONE", "NO_VALID_ZONE",
    "CALL_PENDING", "CALL_ACTIVE", "JUST_RESOLVED", "NEWS", "MARKET_CLOSED",
]
PricePosition = Literal["PREMIUM", "DISCOUNT", "AT_EQ"]


class ThesisRange(Contract):
    lo: float | None = None
    hi: float | None = None
    eq: float | None = None


class ThesisPricePosition(Contract):
    label: PricePosition = "AT_EQ"
    distance_to_eq: float | None = None


class ThesisPlan(Contract):
    side: Literal["LONG", "SHORT"] | None = None
    zone_id: str | None = None
    zone_lo: float | None = None
    zone_hi: float | None = None
    zone_ok: bool = False
    zone_problem: str | None = None


class ThesisGate(Contract):
    code: str
    threshold: float | None = None
    distance: float | None = None
    passed: bool = False


class ThesisInvalidation(Contract):
    level: float | None = None
    rule: str = ""


class ThesisAlternative(Contract):
    trigger_level: float | None = None
    consequence: str = ""


class ThesisDryRun(Contract):
    tf: str
    direction: str
    grade: str = "A"
    grade_notes: list[str] = []
    zone_id: str | None = None
    zone_lo: float | None = None
    zone_hi: float | None = None
    entry_ref: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp1_name: str | None = None
    tp1_pool_id: str | None = None
    reward_r: float | None = None
    min_r: float = 1.5
    first_fail: str | None = None
    passes: bool = False
    gates: list[dict[str, Any]] = []
    distance_to_zone: float | None = None
    target_close_note: str | None = None


class Thesis(Contract):
    tf: str
    bias: str
    bias_since: int | None = None
    bias_cause: dict[str, Any] = {}
    htf_alignment: Literal["agree", "disagree", "undefined"] = "undefined"
    dealing_range: ThesisRange = ThesisRange()
    price_position: ThesisPricePosition = ThesisPricePosition()
    plan: ThesisPlan = ThesisPlan()
    stage: Stage = "NO_BIAS"
    blocking_gate: ThesisGate = ThesisGate(code="NO_BIAS")
    invalidation: ThesisInvalidation = ThesisInvalidation()
    targets: list[dict[str, Any]] = []
    alternative: ThesisAlternative = ThesisAlternative()
    dry_run: ThesisDryRun | None = None
    lines: list[str] = []
    headline: str = ""
    why: str = ""
    if_then: str = ""
    key: str = ""


def _zone_bounds(obj: DrawObject) -> tuple[float, float] | None:
    values = [p.price for p in obj.points if isinstance(p.price, (int, float))]
    if not values:
        return None
    return min(values), max(values)


def _zone_label(obj: DrawObject) -> str:
    tf = str(obj.text_args.get("tf") or "")
    kind = str(obj.text_args.get("kind") or obj.text_args.get("type") or "OB").upper()
    return f"{tf} {kind}".strip()


def _pool_dict(pool: Pool) -> dict[str, Any]:
    return {
        "id": pool.id,
        "name": pool.geometry.name,
        "level": pool.level,
        "state": pool.state,
        "side": pool.geometry.side,
        "strength": pool.strength,
    }


def build_thesis(
    *,
    tf: str,
    price: float | None,
    structure: StructureState | None,
    objects: list[DrawObject],
    pools: list[Pool],
    open_calls: list[Call] | None = None,
    market_closed: bool = False,
    dry_run: Any | None = None,
) -> Thesis:
    open_calls = open_calls or []
    dry = (
        ThesisDryRun.model_validate(
            dry_run.model_dump(mode="json") if hasattr(dry_run, "model_dump") else dry_run
        )
        if dry_run
        else None
    )
    active_call = next((c for c in open_calls if c.state == "ACTIVE"), None)
    pending_call = next((c for c in open_calls if c.state == "PENDING"), None)
    if market_closed:
        return Thesis(tf=tf, bias="UNDEFINED", stage="MARKET_CLOSED", headline="MARKET CLOSED", key="MARKET_CLOSED")
    if active_call or pending_call:
        call = active_call or pending_call
        stage: Stage = "CALL_ACTIVE" if active_call else "CALL_PENDING"
        return Thesis(
            tf=tf,
            bias=call.direction,
            stage=stage,
            headline=f"{call.timeframe or tf} {call.direction} {call.state}",
            plan=ThesisPlan(side=call.direction, zone_id=call.ob_id, zone_lo=call.entry_lo, zone_hi=call.entry_hi, zone_ok=True),
            blocking_gate=ThesisGate(code=stage, threshold=call.effective_entry_ref, distance=(None if price is None else call.effective_entry_ref - price), passed=call.state == "ACTIVE"),
            invalidation=ThesisInvalidation(level=call.invalidation, rule="call stop"),
            targets=[{"id": call.target_pool_id, "level": call.target, "name": "TP1"}],
            key=f"{stage}:{call.id}:{call.state}",
        )
    if structure is None or structure.trend == "UNDEFINED":
        return Thesis(tf=tf, bias="UNDEFINED", stage="NO_BIAS", headline=f"{tf} structure forming", blocking_gate=ThesisGate(code="NO_BIAS"), key="NO_BIAS")

    bias = structure.trend
    side: Literal["LONG", "SHORT"] = "LONG" if bias == "BULLISH" else "SHORT"
    lo = structure.protected_low if bias == "BULLISH" else structure.major_low
    hi = structure.major_high if bias == "BULLISH" else structure.protected_high
    eq = (lo + hi) / 2 if lo is not None and hi is not None and hi > lo else None
    if eq is None:
        return Thesis(tf=tf, bias=bias, bias_since=structure.trend_since_ms, stage="NO_BIAS", headline=f"{tf} {bias} / range forming", key=f"{bias}:NO_RANGE")
    current = price if price is not None else eq
    if abs(current - eq) <= 1e-9:
        position: PricePosition = "AT_EQ"
    elif current > eq:
        position = "PREMIUM"
    else:
        position = "DISCOUNT"
    desired_position: PricePosition = "PREMIUM" if side == "SHORT" else "DISCOUNT"
    gate_passed = position == desired_position or position == "AT_EQ"

    zones: list[tuple[DrawObject, float, float]] = []
    for obj in objects:
        if obj.shape != "ZONE" or obj.state == "INVALID" or obj.style.token not in {"zone.ob", "zone.fvg", "call.trade"}:
            continue
        bounds = _zone_bounds(obj)
        if bounds:
            zones.append((obj, bounds[0], bounds[1]))
    preferred = []
    for obj, zlo, zhi in zones:
        direction = str(obj.text_args.get("direction") or "").upper()
        if (side == "SHORT" and direction == "BEARISH") or (side == "LONG" and direction == "BULLISH"):
            preferred.append((obj, zlo, zhi))
    if not preferred:
        preferred = zones
    preferred.sort(key=lambda row: abs(((row[1] + row[2]) / 2) - current))
    zone_obj, zone_lo, zone_hi = preferred[0] if preferred else (None, None, None)

    zone_ok = False
    zone_problem: str | None = None
    if zone_obj is None or zone_lo is None or zone_hi is None:
        zone_problem = "entry zone pending"
    elif side == "SHORT":
        if zone_hi > hi:
            zone_problem = f"{_zone_label(zone_obj)} above protected high {hi:.2f}"
        elif zone_lo < eq:
            zone_problem = f"{_zone_label(zone_obj)} below EQ {eq:.2f}"
        else:
            zone_ok = True
    else:
        if zone_lo < lo:
            zone_problem = f"{_zone_label(zone_obj)} below protected low {lo:.2f}"
        elif zone_hi > eq:
            zone_problem = f"{_zone_label(zone_obj)} above EQ {eq:.2f}"
        else:
            zone_ok = True

    target_pools = [p for p in pools if p.state in ("FRESH", "TOUCHED") and ((side == "SHORT" and p.level < current) or (side == "LONG" and p.level > current))]
    target_pools.sort(key=lambda p: abs(p.level - current))
    invalidation_level = hi if side == "SHORT" else lo
    invalidation_rule = "close above protected_high" if side == "SHORT" else "close below protected_low"
    stage: Stage
    if not zone_ok:
        stage = "NO_VALID_ZONE"
    elif gate_passed:
        in_zone = zone_lo <= current <= zone_hi if zone_lo is not None and zone_hi is not None else False
        stage = "PRICE_AT_ZONE" if in_zone else "WAITING_FOR_PRICE"
    else:
        stage = "WAITING_FOR_PRICE"
    if not zone_ok:
        gate_code = "ZONE_INVALID"
        gate_threshold = eq
        gate_distance = abs(current - eq)
    elif stage == "PRICE_AT_ZONE":
        gate_code = "PRICE_AT_ZONE"
        gate_threshold = current
        gate_distance = 0.0
    elif not gate_passed:
        gate_code = f"WAIT_{desired_position}"
        gate_threshold = eq
        gate_distance = abs(current - eq)
    else:
        gate_code = "WAIT_ZONE_RETURN"
        if zone_lo is not None and zone_hi is not None:
            if current < zone_lo:
                gate_threshold = zone_lo
                gate_distance = zone_lo - current
            elif current > zone_hi:
                gate_threshold = zone_hi
                gate_distance = current - zone_hi
            else:
                gate_threshold = current
                gate_distance = 0.0
        else:
            gate_threshold = eq
            gate_distance = abs(current - eq)
    headline = (
        f"{tf} {bias} / {position.lower()} / no valid {'short' if side == 'SHORT' else 'long'} zone"
        if stage == "NO_VALID_ZONE"
        else f"{tf} {bias} / {position.lower()} / waiting for {desired_position.lower()}"
        if not gate_passed
        else f"{tf} {bias} / {position.lower()} / watching zone"
    )
    event = structure.last_event
    bias_cause = {
        "event_id": event.id if event else None,
        "kind": event.kind if event else None,
        "level": event.level if event else None,
        "t_ms": event.t_ms if event else None,
    }
    why = f"{bias} since {event.kind if event else 'structure'} {event.level:.2f}" if event else f"{bias} structure"
    target = target_pools[0] if target_pools else None
    alternative = ThesisAlternative(
        trigger_level=target.level if target else None,
        consequence=(f"next target {target.geometry.name}" if target else "target pending"),
    )
    if_then = (
        f"Close < {target.level:.2f} / {alternative.consequence}  Close > {hi:.2f} / bearish view off"
        if side == "SHORT" and target
        else f"Close > {target.level:.2f} / {alternative.consequence}  Close < {lo:.2f} / bullish view off"
        if side == "LONG" and target
        else f"Invalidation {invalidation_rule}"
    )
    if dry and dry.reward_r is not None:
        if not dry.passes and dry.first_fail == "R_MIN" and dry.tp1 is not None:
            r_line = (
                f"R {dry.reward_r:.1f} < {dry.min_r:.1f}  "
                f"target {dry.tp1_name or 'TP1'} {dry.tp1:.2f} too close"
            )
        elif dry.passes and dry.tp1 is not None:
            r_line = f"R {dry.reward_r:.1f} TP1 {dry.tp1_name or 'TP1'} {dry.tp1:.2f}"
        else:
            r_line = f"R {dry.reward_r:.1f} blocked by {str(dry.first_fail).replace('_' , ' ').lower()}"
    elif dry and dry.first_fail:
        r_line = f"Gate blocked: {str(dry.first_fail).replace('_' , ' ').lower()}"
    else:
        if zone_obj:
            r_line = "R blocked: no validated OB"
        else:
            r_line = "R check: no planned zone"
    if dry and dry.target_close_note:
        r_line = f"{r_line}  {dry.target_close_note}"
    if dry and not dry.passes and dry.first_fail in {"R_MIN", "STOP_CAP", "TARGET_FOUND", "TARGET_MAX_R"}:
        fail = str(dry.first_fail).replace("_", " ").lower()
        if dry.first_fail == "R_MIN" and dry.reward_r is not None:
            headline = (
                f"{tf} {bias} / zone {dry.zone_lo:.2f}-{dry.zone_hi:.2f} "
                f"fails R {dry.reward_r:.1f} < {dry.min_r:.1f}"
            )
        else:
            headline = f"{tf} {bias} / zone blocked by {fail}"
    lines = [
        f"{bias} bias active",
        f"Price in {position.lower()} ({current:.2f} {'>' if current > eq else '<' if current < eq else '='} EQ {eq:.2f})",
        (f"Producer zone {dry.zone_lo:.2f}-{dry.zone_hi:.2f}" if dry else f"Only {_zone_label(zone_obj)} {zone_lo:.2f}-{zone_hi:.2f} {zone_problem}" if zone_obj and zone_problem else f"Zone {_zone_label(zone_obj)} {zone_lo:.2f}-{zone_hi:.2f}" if zone_obj else "Entry zone pending"),
        r_line,
        f"Target: {target.geometry.name} {target.level:.2f}" if target else "Target: no eligible pool",
    ]
    key = content_hash((tf, bias, stage, gate_code, zone_obj.id if zone_obj else None, position))
    return Thesis(
        tf=tf,
        bias=bias,
        bias_since=structure.trend_since_ms,
        bias_cause=bias_cause,
        dealing_range=ThesisRange(lo=lo, hi=hi, eq=eq),
        price_position=ThesisPricePosition(label=position, distance_to_eq=current - eq),
        plan=ThesisPlan(side=side, zone_id=dry.zone_id if dry else (zone_obj.id if zone_obj else None), zone_lo=dry.zone_lo if dry else zone_lo, zone_hi=dry.zone_hi if dry else zone_hi, zone_ok=(dry.passes if dry else zone_ok), zone_problem=(dry.first_fail if dry and not dry.passes else zone_problem)),
        stage=stage,
        blocking_gate=ThesisGate(code=gate_code, threshold=gate_threshold, distance=gate_distance, passed=gate_passed and zone_ok),
        invalidation=ThesisInvalidation(level=invalidation_level, rule=invalidation_rule),
        targets=[_pool_dict(p) for p in target_pools[:3]],
        alternative=alternative,
        headline=headline,
        why=why,
        if_then=if_then,
        dry_run=dry,
        lines=lines,
        key=key,
    )


