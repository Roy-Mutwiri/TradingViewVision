from types import SimpleNamespace

from oracle.analysis.contracts import Call
from oracle.analysis.producer import CallProducer
from oracle.config import CallsConfig, GradeBConfig, TradeConfig
from oracle.models import Bar
from oracle.smc.liquidity_contracts import LiquidityGeometry, Pool
from oracle.smc.ob_contracts import OBGeometry, OBRecord
from oracle.smc.structure import StructureEvent, StructureState


def evidence(direction="BULLISH", lo=92, hi=94):
    b = Bar(
        tf="M15",
        t_open_ms=1700000000000,
        o=94,
        h=97,
        l=91,
        c=96,
        tick_volume=1,
        source="synthetic",
        complete=True,
        digits=2,
    )
    up = direction == "BULLISH"
    e = StructureEvent(
        id="evt",
        kind="BOS",
        direction="UP" if up else "DOWN",
        level=95,
        broken_swing_id="s",
        broken_swing_idx=0,
        break_bar_idx=2,
        break_close=96,
        timeframe="M15",
        trend_before="BULLISH" if up else "BEARISH",
        trend_after="BULLISH" if up else "BEARISH",
        atr_at_break=2,
        t_ms=b.t_open_ms,
        source_bars=(0, 1, 2),
        source_object_ids=("a", "b", "c"),
    )
    g = OBGeometry(
        tf="M15",
        direction=direction,
        price_lo=lo,
        price_hi=hi,
        ce=(lo + hi) / 2,
        size=hi - lo,
        atr_at_creation=2,
        created_ms=b.t_open_ms,
        t_start_ms=b.t_open_ms - 900000,
        created_idx=2,
        origin_idx=0,
        leg_start_idx=1,
        boundary="body_to_wick",
        displacement_atr=2,
        source_bars=(0, 1, 2),
        source_object_ids=("a", "b", "c"),
        fvg_ids=("f",),
    )
    ob = OBRecord(
        geometry=g,
        validated_by_event_id="evt",
        validation_event_ids=("evt",),
        validation_kind="BOS",
    )
    state = StructureState(
        trend="BULLISH" if up else "BEARISH",
        major_high=110 if up else 100,
        major_high_idx=1,
        major_high_id="h",
        major_low=90 if up else 80,
        major_low_idx=0,
        major_low_id="l",
        protected_low=90,
        protected_high=100,
        last_event=e,
    )
    level = 99 if up else 87
    pg = LiquidityGeometry(
        tf="M15",
        direction="BEARISH" if up else "BULLISH",
        side="HIGH" if up else "LOW",
        name="EQH" if up else "EQL",
        level=level,
        price_lo=level,
        price_hi=level,
        ce=level,
        atr_at_creation=2,
        created_ms=b.t_open_ms - 1,
        t_start_ms=b.t_open_ms - 1,
        source_bars=(0, 1),
        source_object_ids=("p", "q"),
    )
    pool = Pool(id="pool", geometry=pg, strength=2)
    liq = SimpleNamespace(
        sweeps=[],
        pools_above=lambda p, tf: [pool] if up else [],
        pools_below=lambda p, tf: [pool] if not up else [],
    )
    return b, ob, state, liq


def test_constructs_falsifiable_call_with_evidence_and_r_gate():
    b, ob, state, liq = evidence()
    p = CallProducer(TradeConfig(), CallsConfig())
    call = p.construct(
        ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
    )
    assert (
        call
        and call.reward_r >= 1.5
        and call.ob_id == ob.id
        and call.structure_event_id == "evt"
        and call.target_pool_id == "pool"
    )
    assert call.invalidation < call.entry_lo < call.target and call.in_ote is not None
    assert call.entry_ref == call.entry_hi


def test_long_premium_and_short_discount_are_rejected():
    b, ob, state, liq = evidence(lo=96, hi=98)
    p = CallProducer(TradeConfig(), CallsConfig(grade_b=GradeBConfig(enabled=False)))
    assert (
        p.construct(
            ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
        )
        is None
    )
    b, ob, state, liq = evidence("BEARISH", 86, 88)
    p = CallProducer(TradeConfig(), CallsConfig(grade_b=GradeBConfig(enabled=False)))
    assert (
        p.construct(
            ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
        )
        is None
    )
    assert p.rejections["WRONG_RANGE_HALF"] == 1


def test_loss_spends_zone_and_concurrency_rejects_duplicates():
    b, ob, state, liq = evidence()
    p = CallProducer(TradeConfig(), CallsConfig())
    call = p.construct(
        ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
    )
    assert call
    lost = Call.model_validate(
        call.model_dump() | {"state": "LOSS", "resolved_ms": call.created_ms + 60000}
    )
    p.mark_resolution(lost)
    p.used_zones.clear()
    assert (
        p.construct(
            ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
        )
        is None
    )
    assert p.rejections["ZONE_SPENT"] == 1


def test_concurrency_suppresses_same_tf_and_opposing_calls():
    b, ob, state, liq = evidence()
    p = CallProducer(TradeConfig(), CallsConfig())
    active = p.construct(
        ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
    )
    assert active
    p.used_zones.clear()
    # A published but unfilled call consumes only the pending queue.
    second = p.construct(
        ob=ob,
        fvgs=[],
        structure=state,
        liquidity=liq,
        bar=b,
        atr=2,
        clock_version=1,
        active=[active],
    )
    assert second is not None
    second = second.model_copy(update={"id": "second-pending-call"})
    active = active.model_copy(update={"state": "ACTIVE", "trigger_price": active.entry_ref})
    assert not p.can_activate(second, [active, second])
    assert p.can_activate(second, [second])
    p.used_zones.clear()
    assert (
        p.construct(
            ob=ob,
            fvgs=[],
            structure=state,
            liquidity=liq,
            bar=b,
            atr=2,
            clock_version=1,
            active=[active],
        )
        is None
    )
    assert p.rejections["CONCURRENT_SAME_TF"] == 1
    b2, ob2, state2, liq2 = evidence("BEARISH", 96, 98)
    p.used_zones.clear()
    assert (
        p.construct(
            ob=ob2,
            fvgs=[],
            structure=state2,
            liquidity=liq2,
            bar=b2,
            atr=2,
            clock_version=1,
            active=[active],
        )
        is None
    )
    assert p.rejections["OPPOSING_HTF_CALL"] == 1


def test_eq_or_pool_chooses_closer_eligible_objective_and_caps_r():
    b, ob, state, liq = evidence()
    p = CallProducer(TradeConfig(), CallsConfig())
    pool_call = p.construct(
        ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
    )
    assert pool_call and pool_call.target == 99 and pool_call.tp2 is None
    # Move EQ between the entry and pool while keeping at least 1.5R available.
    closer = state.model_copy(update={"major_high": 106})
    p.used_zones.clear()
    eq_call = p.construct(
        ob=ob, fvgs=[], structure=closer, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
    )
    assert eq_call and eq_call.target == 98 and eq_call.tp2 == 99
    assert eq_call.reward_r <= p.trade.max_tp_r
    p.used_zones.clear()
    assert (
        CallProducer(TradeConfig(max_tp_r=1.6), CallsConfig()).construct(
            ob=ob,
            fvgs=[],
            structure=closer,
            liquidity=liq,
            bar=b,
            atr=2,
            clock_version=1,
            active=[],
        )
        is None
    )


def test_pending_has_separate_cap_and_expiry_is_six_bars():
    b, ob, state, liq = evidence()
    p = CallProducer(TradeConfig(), CallsConfig(max_pending=1))
    first = p.construct(
        ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
    )
    assert first
    p.used_zones.clear()
    assert (
        p.construct(
            ob=ob,
            fvgs=[],
            structure=state,
            liquidity=liq,
            bar=b,
            atr=2,
            clock_version=1,
            active=[first],
        )
        is None
    )
    assert p.rejections["PENDING_TOTAL"] == 1
    assert first.expires_ms - first.created_ms == 6 * 15 * 60_000


def test_higher_timeframe_arbitration_never_retires_a_published_call():
    b, ob, state, liq = evidence()
    p = CallProducer(TradeConfig(), CallsConfig())
    low = p.construct(
        ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[]
    )
    assert low
    higher, cancelled = p.htf_arbitration([low], "SHORT", "H1")
    assert higher == [low] and cancelled == []
    active = low.model_copy(update={"state": "ACTIVE"})
    kept, cancelled = p.htf_arbitration([active], "SHORT", "H1")
    assert kept == [active] and cancelled == []


def test_grade_b_allows_zone_touch_with_wrong_range_half_without_changing_a_ids():
    b, ob, state, _ = evidence("BEARISH", 86, 88)
    b = b.model_copy(update={"l": 86, "c": 87})
    pg = LiquidityGeometry(
        tf="M15", direction="BULLISH", side="LOW", name="EQL", level=82,
        price_lo=82, price_hi=82, ce=82, atr_at_creation=2,
        created_ms=b.t_open_ms - 1, t_start_ms=b.t_open_ms - 1,
        source_bars=(0, 1), source_object_ids=("p", "q"),
    )
    pool = Pool(id="pool-b", geometry=pg, strength=2)
    liq = SimpleNamespace(sweeps=[], pools_above=lambda p, tf: [], pools_below=lambda p, tf: [pool])
    p = CallProducer(TradeConfig(), CallsConfig())
    call = p.construct(ob=ob, fvgs=[], structure=state, liquidity=liq, bar=b, atr=2, clock_version=1, active=[])
    assert call and call.grade == "B"
    assert "in discount" in call.grade_notes
    assert call.reward_r >= 1.5
    a_bar, a_ob, a_state, a_liq = evidence()
    a_call = CallProducer(TradeConfig(), CallsConfig()).construct(ob=a_ob, fvgs=[], structure=a_state, liquidity=a_liq, bar=a_bar, atr=2, clock_version=1, active=[])
    a_clone = Call.model_validate(a_call.model_dump())
    assert a_clone.id == a_call.id and a_call.grade == "A"

