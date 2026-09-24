from oracle.models import Animation, DrawObject, Point, Style
from oracle.smc.liquidity_contracts import LiquidityGeometry, Pool
from oracle.smc.structure import StructureEvent, StructureState
from oracle.thesis import build_thesis


def zone(lo: float, hi: float) -> DrawObject:
    return DrawObject(
        layer="L2",
        shape="ZONE",
        points=[Point(t_ms=1, price=lo), Point(t_ms=2, price=hi)],
        style=Style(token="zone.ob"),
        text_key="zone.ob",
        text_args={"tf": "M15", "kind": "OB", "direction": "BEARISH"},
        state="FRESH",
        ttl_ms=0,
        priority=1,
        z=1,
        anim=Animation(in_="none", loop=None),
        reason="test OB",
        source_bars=[1],
        confidence=1,
    )


def pool(name: str, level: float, side: str) -> Pool:
    return Pool(
        id=f"pool-{name}",
        geometry=LiquidityGeometry(
            tf="M15",
            direction="BULLISH" if side == "LOW" else "BEARISH",
            side=side,
            name=name,
            level=level,
            price_lo=level,
            price_hi=level,
            ce=level,
            atr_at_creation=1,
            created_ms=1,
            t_start_ms=1,
            source_bars=(1,),
            source_object_ids=("x",),
        ),
        strength=1,
    )


def test_thesis_rejects_short_zone_above_protected_high_without_waiting() -> None:
    event = StructureEvent(
        id="evt",
        kind="BOS",
        direction="DOWN",
        level=4315.33,
        broken_swing_id="swing",
        broken_swing_idx=1,
        break_bar_idx=2,
        break_close=4314,
        timeframe="M15",
        trend_before="BEARISH",
        trend_after="BEARISH",
        atr_at_break=5,
        t_ms=10,
        source_bars=(1, 2),
        source_object_ids=("a", "b"),
    )
    state = StructureState(
        trend="BEARISH",
        major_low=4308.23,
        protected_high=4320.54,
        last_event=event,
        trend_since_ms=1,
    )
    thesis = build_thesis(
        tf="M15",
        price=4316.30,
        structure=state,
        objects=[zone(4322.64, 4331.45)],
        pools=[pool("LONDON L", 4308.23, "LOW")],
    )
    assert thesis.dealing_range.eq == (4308.23 + 4320.54) / 2
    assert thesis.price_position.label == "PREMIUM"
    assert thesis.blocking_gate.passed is False
    assert thesis.stage == "NO_VALID_ZONE"
    assert thesis.plan.zone_problem is not None
    assert "protected high" in thesis.plan.zone_problem
    assert "waiting" not in thesis.headline.lower()
