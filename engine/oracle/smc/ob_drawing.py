"""OB DrawObjects only. Renderer projection cannot change analysis geometry."""

from oracle.models import Animation, DrawObject, Point, Style, timeframe_ms
from oracle.smc.ob_contracts import OBGeometry
from oracle.smc.order_blocks import OrderBlockEngine


def ob_objects(engine: OrderBlockEngine, end_ms: int) -> list[DrawObject]:
    records = sorted(
        (
            r
            for r in engine.records
            if r.state not in ("INVALID", "MERGED")
            and not (
                r.state == "MITIGATED"
                and r.mitigated_ms is not None
                and end_ms - r.mitigated_ms
                > engine.config.zone_ttl_bars * timeframe_ms(r.geometry.tf)
            )
        ),
        key=lambda r: (r.geometry.created_ms, r.id),
    )
    candidates = [c for c in engine.candidates.values() if c.state == "CANDIDATE"]
    capacity = max(0, engine.config.max_visible_per_tf.ob - len(candidates[-3:]))
    selected: list[
        tuple[
            OBGeometry, str, bool, str, str | None, str | None, str | None, str | None, int | None
        ]
    ] = [
        (
            r.geometry,
            r.id,
            True,
            r.state,
            None,
            None,
            None,
            r.validation_kind,
            r.mitigated_bar_open_ms or r.mitigated_ms,
        )
        for r in (records[-capacity:] if capacity else [])
    ]
    selected += [
        (
            c.geometry,
            c.id,
            False,
            "INVALID" if c.state == "DISCARDED" else "FRESH",
            c.state,
            c.reason,
            c.criterion,
            None,
            None,
        )
        for c in [
            *candidates[-3:],
            *[v for v in engine.candidates.values() if v.state == "DISCARDED"][-32:],
        ]
    ]
    objects = []
    for g, oid, confirmed, state, lifecycle, reason, criterion, validation, mitigated in selected:
        c = engine.candidates.get(oid)
        objects.append(
            DrawObject.model_validate(
                dict(
                    layer="L2",
                    shape="ZONE",
                    points=[
                        Point(t_ms=g.t_start_ms, price=g.price_lo),
                        Point(t_ms=g.created_ms, price=g.price_hi),
                    ],
                    style=Style(token="zone.ob"),
                    text_key=f"ob.{oid}",
                    text_args=dict(
                        zone_id=oid,
                        kind="OB",
                        tf=g.tf,
                        direction=g.direction,
                        confirmed=confirmed,
                        lifecycle=lifecycle,
                        discard_reason=reason,
                        failed_criterion=criterion,
                        decision_id=c.decision_id if c else "",
                        unfilled_lo=g.price_lo,
                        unfilled_hi=g.price_hi,
                        ce=g.ce,
                        strength=len(g.constituent_ids) or 1,
                        end_ms=mitigated if state == "MITIGATED" and mitigated else end_ms,
                        ob_state=state,
                        validation_kind=validation,
                        opacity=0.35 if state == "MITIGATED" else 1,
                    ),
                    state=state,
                    ttl_ms=0,
                    priority=4,
                    z=0,
                    anim=Animation(in_="none", loop=None),
                    source_bars=list(g.source_bars),
                    confidence=1 if confirmed else 0,
                    reason="Four-criterion order block"
                    if confirmed
                    else "Unconfirmed OB; no call evidence",
                    digits=2,
                )
            )
        )
    return objects
