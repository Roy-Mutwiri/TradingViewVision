"""Liquidity projected through the existing DrawObject layer and label pass."""

from oracle.models import Animation, DrawObject, Point, Style, timeframe_ms
from oracle.smc.liquidity import LiquidityEngine
from oracle.smc.liquidity_contracts import Pool


def visible_pools(engine: LiquidityEngine, price: float) -> list[Pool]:
    values = [engine.pools[oid] for oid in engine.active if engine.pools[oid].state != "BROKEN"]
    atr = engine.current_atr or (values[0].geometry.atr_at_creation if values else 1)
    # Nearby named levels receive the first slots, then strength/proximity ranking.
    return sorted(
        values,
        key=lambda p: (
            not (
                p.id in engine.pending
                or p.id in engine.named.values()
                and abs(p.level - price) <= atr
            ),
            -p.strength / (1 + abs(p.level - price) / atr),
            abs(p.level - price),
            p.id,
        ),
    )[: engine.config.max_pools_visible]


def liquidity_objects(
    engine: LiquidityEngine, end_ms: int, price: float, bar_idx: int
) -> list[DrawObject]:
    result = []
    selected = visible_pools(engine, price)
    for pool in selected:
        g = pool.geometry
        c = next(
            (
                c
                for c in engine.candidates.values()
                if c.pool_id == pool.id and c.state == "CANDIDATE"
            ),
            None,
        )
        result.append(
            DrawObject(
                layer="L2",
                shape="LINE",
                points=[
                    Point(t_ms=g.t_start_ms, price=g.level),
                    Point(t_ms=g.created_ms, price=g.level),
                ],
                style=Style(token="liquidity.pool"),
                text_key=f"liquidity.{pool.id}",
                text_args=dict(
                    zone_id=pool.id,
                    pool_id=pool.id,
                    tf=g.tf,
                    name=g.name,
                    strength=pool.strength,
                    pool_state=pool.state,
                    kind="SWEEP" if pool.state == "SWEPT" else "POOL",
                    confirmed_at_ms=pool.swept_ms,
                    end_ms=end_ms,
                    unfilled_lo=g.level,
                    unfilled_hi=g.level,
                    ce=g.level,
                    touch_times=list(pool.touch_times),
                    confirmed=c is None,
                    lifecycle="CANDIDATE" if c else "CONFIRMED",
                    candidate_id=c.id if c else None,
                    decision_id=c.decision_id if c else None,
                    bars_left=max(0, engine.config.sweep_reclaim_bars - (bar_idx - c.born_bar_idx))
                    if c
                    else None,
                    opacity=0.35
                    if pool.state == "SWEPT"
                    else 0.7
                    if pool.state == "TOUCHED"
                    else 1,
                    swept_ms=pool.swept_ms,
                    sweep_event_id=pool.sweep_event_id,
                    label_at_end=True,
                    side=g.side,
                ),
                reason="Confirmed liquidity geometry; wick raid awaits closed-body reclaim"
                if c
                else "Confirmed pool; targets exclude swept and broken levels",
                confidence=0 if c else 1,
                source_bars=list(g.source_bars),
                state="FRESH",
                ttl_ms=0,
                priority=3,
                z=1,
                anim=Animation(in_="none", loop=None),
            )
        )
    for c in [c for c in engine.candidates.values() if c.state == "DISCARDED"][-32:]:
        g = c.geometry
        result.append(
            DrawObject(
                layer="L2",
                shape="LINE",
                points=[
                    Point(t_ms=g.t_start_ms, price=g.level),
                    Point(t_ms=g.created_ms, price=g.level),
                ],
                style=Style(token="liquidity.pool"),
                text_key=f"liquidity.discard.{c.id}",
                text_args=dict(
                    zone_id=c.id,
                    pool_id=c.pool_id,
                    tf=g.tf,
                    name=g.name,
                    end_ms=end_ms,
                    unfilled_lo=g.level,
                    unfilled_hi=g.level,
                    ce=g.level,
                    confirmed=False,
                    lifecycle="DISCARDED",
                    discard_reason=c.reason,
                    decision_id=c.decision_id,
                    label_at_end=True,
                ),
                reason="Pending sweep discarded with logged reason",
                confidence=0,
                source_bars=list(g.source_bars),
                state="INVALID",
                ttl_ms=0,
                priority=3,
                z=1,
                anim=Animation(in_="none", loop=None),
            )
        )
    for s in engine.sweeps[-6:]:
        if s.pool_id not in {p.id for p in selected}:
            continue
        pool = engine.pools[s.pool_id]
        result.append(
            DrawObject(
                layer="L2",
                shape="LABEL",
                points=[Point(t_ms=s.reclaim_ms - timeframe_ms(engine.tf), price=s.level)],
                style=Style(token="liquidity.reclaim"),
                text_key=f"reclaim.{s.id}",
                text_args=dict(tf=engine.tf, confirmed=True, sweep_event_id=s.id, side=s.side),
                reason="Confirmed body reclaimed the swept pool",
                confidence=1,
                source_bars=list(s.source_bars),
                state="FRESH",
                ttl_ms=0,
                priority=2,
                z=1,
                anim=Animation(in_="none", loop=None),
            )
        )
    return result
