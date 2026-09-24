"""Call DrawObjects use the existing chart object contract."""

from oracle.analysis.contracts import CallRow
from oracle.models import Animation, DrawObject, Point, Style, timeframe_ms


def call_objects(rows: list[CallRow], end_ms: int, price: float, broadcast_mode: str = "paper") -> list[DrawObject]:
    out = []
    for row in rows[-10:]:
        c = row.call
        hold_ms = 600 if c.state == "CANCELLED" else 8_000
        if c.created_ms > end_ms:
            continue
        if c.state not in ("PENDING", "ACTIVE"):
            if c.resolved_ms is None:
                continue
            resolved_age_ms = end_ms - c.resolved_ms
            if resolved_age_ms < 0 or resolved_age_ms > hold_ms:
                continue
        entry_distance = abs(c.effective_entry_ref - price)
        stop_hit = (
            price <= c.invalidation if c.direction == "LONG" else price >= c.invalidation
        )
        tp1_hit = price >= c.target if c.direction == "LONG" else price <= c.target
        tp2_hit = (
            False
            if c.tp2 is None
            else (price >= c.tp2 if c.direction == "LONG" else price <= c.tp2)
        )
        live_phase = "TRACKING"
        if c.state == "ACTIVE":
            if stop_hit:
                live_phase = "SL_HIT_SEARCHING"
            elif tp2_hit:
                live_phase = "TP2_HIT_SEARCHING"
            elif tp1_hit:
                live_phase = "TP1_HIT_WAITING_TP2" if c.tp2 is not None else "TP1_HIT"
        elif c.state == "WIN" and c.tp2 is not None and not tp2_hit:
            live_phase = "TP1_HIT_WAITING_TP2"
        elif c.state == "LOSS":
            live_phase = "SL_HIT_SEARCHING"
        elif c.state == "WIN" and tp2_hit:
            live_phase = "TP2_HIT_SEARCHING"
        color = "BULLISH" if c.direction == "LONG" else "BEARISH"
        tf_ms = timeframe_ms(c.timeframe or "M15")
        bars_remaining = max(0, (c.expires_ms - end_ms + tf_ms - 1) // tf_ms)
        common = dict(
            call_id=c.id,
            zone_id=c.id,
            call_state=c.state,
            direction=color,
            tf=c.timeframe or "M15",
            end_ms=end_ms,
            entry_lo=c.entry_lo,
            entry_hi=c.entry_hi,
            entry_mid=c.effective_entry_ref,
            stop=c.invalidation,
            tp1=c.target,
            tp2=c.tp2,
            reward_r=c.reward_r,
            entry_distance=entry_distance,
            too_far=c.state == "PENDING" and entry_distance > 3.0,
            live_phase=live_phase,
            bars_remaining=bars_remaining,
            broadcast_mode=broadcast_mode,
            grade=c.grade,
            grade_notes=list(c.grade_notes),
            stop_hit=stop_hit,
            tp1_hit=tp1_hit,
            tp2_hit=tp2_hit,
            live_r=((price - c.effective_entry_ref) if c.direction == "LONG" else (c.effective_entry_ref - price))
            / c.risk,
            resolution_reason=row.cancellation_reason or row.resolution_reason,
            lifecycle="DISCARDED" if c.state == "CANCELLED" else "CONFIRMED",
            discard_reason=row.cancellation_reason if c.state == "CANCELLED" else None,
            decision_id=f"call-cancel:{c.id}:{c.resolved_ms}" if c.state == "CANCELLED" else "",
        )
        out.append(
            DrawObject.model_validate(
                dict(
                    layer="L2",
                    shape="ZONE",
                    points=[
                        Point(t_ms=c.created_ms, price=c.entry_lo),
                        Point(t_ms=end_ms, price=c.entry_hi),
                    ],
                    style=Style(token="call.trade"),
                    text_key=f"call.{c.id}",
                    text_args=common,
                    state="FRESH",
                    ttl_ms=0,
                    priority=10,
                    z=2,
                    anim=Animation(in_="wipe", loop=None),
                    source_bars=list(c.source_bars) or [0],
                    confidence=1,
                    reason=c.reason,
                    digits=2,
                )
            )
        )

        for role, value in (("ENTRY", c.effective_entry_ref), ("SL", c.invalidation), ("TP1", c.target)):
            out.append(
                DrawObject.model_validate(
                    dict(
                        layer="L3",
                        shape="LABEL",
                        points=[Point(t_ms=end_ms, price=value)],
                        style=Style(token="call.level"),
                        text_key=f"call.{role.lower()}.{c.id}",
                        text_args=dict(common, level_role=role),
                        state="FRESH",
                        ttl_ms=0,
                        priority=10,
                        z=3,
                        anim=Animation(in_="fade", loop=None),
                        source_bars=list(c.source_bars) or [0],
                        confidence=1,
                        reason=c.reason,
                        digits=2,
                    )
                )
            )
        if end_ms - c.created_ms <= 20_000:
            out.append(
                DrawObject.model_validate(
                    dict(
                        layer="L3",
                        shape="LABEL",
                        points=[Point(t_ms=c.created_ms, price=c.effective_entry_ref)],
                        style=Style(token="analysis.reason"),
                        text_key=f"call.reason.{c.id}",
                        text_args={"label": "\n".join(c.reason_chain[:3]), "state": c.state},
                        state="FRESH",
                        ttl_ms=20_000,
                        priority=10,
                        z=3,
                        anim=Animation(in_="fade", loop=None),
                        source_bars=list(c.source_bars) or [0],
                        confidence=1,
                        reason=c.reason,
                        digits=2,
                    )
                )
            )
    return out
