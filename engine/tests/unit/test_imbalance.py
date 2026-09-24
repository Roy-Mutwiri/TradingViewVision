import json
import random
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from oracle.config import ZonesConfig
from oracle.indicators.ut_bot import rma_atr
from oracle.models import Bar
from oracle.smc.imbalance import (
    FVGGeometry,
    FVGRecord,
    ImbalanceCursor,
    advance_fvg,
    advance_imbalance,
    build_fvg_union,
    create_fvg_record,
    detect_fvg,
    merge_fvgs,
    observe_fill,
    plan_fvg_merges,
)

BASE = 1700000100000
STEP = 900000


def candle(i, o, h, low, c, *, complete=True):
    return Bar(tf="M15", t_open_ms=BASE+i*STEP, o=o, h=h, l=low, c=c,
               tick_volume=10, source="synthetic", complete=complete, digits=3)


@pytest.fixture
def triples():
    raw=json.loads((Path(__file__).parents[1]/"fixtures/synthetic/fvg_three_candles.json").read_text())
    return {kind:[candle(i,*row) for i,row in enumerate(raw[kind])]
            for kind in ("bullish","bearish")}


def test_exact_three_candle_gaps_ce_size_and_provenance(triples):
    for kind, direction, bounds in (("bullish","BULLISH",(101,104)),("bearish","BEARISH",(96,99))):
        sample=triples[kind]
        gap=detect_fvg(sample,atr=10)
        assert gap.direction==direction
        assert (gap.price_lo,gap.price_hi)==bounds
        assert gap.ce==sum(bounds)/2 and gap.size==3
        assert gap.created_ms==sample[2].t_open_ms+STEP
        assert gap.source_bars==(0,1,2)
        assert gap.source_object_ids==tuple(b.id for b in sample)
        assert FVGGeometry.model_validate_json(gap.canonical_json())==gap
        with pytest.raises(ValidationError):
            gap.price_hi=500


def test_atr_gate_is_inclusive_and_missing_atr_never_guessed(triples):
    sample=triples["bullish"]
    assert detect_fvg(sample,atr=15) is not None  # size 3 == 0.2 * 15
    assert detect_fvg(sample,atr=15.001) is None
    assert detect_fvg(sample,atr=None) is None
    assert detect_fvg(sample,atr=30,config=ZonesConfig(fvg_min_atr=.10)) is not None
    for value in (0,-1,float("inf"),float("nan")):
        with pytest.raises(ValueError,match="ATR"):
            detect_fvg(sample,atr=value)


def test_touching_edges_is_not_a_gap_and_forming_c3_never_creates_one(triples):
    sample=triples["bullish"]
    touching=[*sample[:2],candle(2,103,108,101,106)]
    assert detect_fvg(touching,atr=10) is None
    for i in range(3):
        forming=[Bar.model_validate(b.model_dump()|{"complete":False,"id":"","object_hash":""}) if j==i else b
                 for j,b in enumerate(sample)]
        assert detect_fvg(forming,atr=10) is None


def test_bullish_half_fill_by_wick_and_ce_respected(triples):
    gap=detect_fvg(triples["bullish"],atr=10)
    observation=observe_fill(gap,candle(3,104,106,102.5,103.5),bar_idx=3)
    assert observation.fill_pct==.5
    assert observation.unfilled==(101,102.5)
    assert observation.ce_status=="RESPECTED"
    assert not observation.body_beyond_far_edge
    assert not observation.inversion_confirmed


def test_bearish_half_fill_and_mirrored_ce(triples):
    gap=detect_fvg(triples["bearish"],atr=10)
    observation=observe_fill(gap,candle(3,96,97.5,94,96.5),bar_idx=3)
    assert observation.fill_pct==.5 and observation.unfilled==(97.5,99)
    assert observation.ce_status=="RESPECTED"
    weakened=observe_fill(gap,candle(4,97,98.5,96,98),bar_idx=4,previous_fill=.5)
    assert weakened.ce_status=="WEAKENED" and weakened.fill_pct==pytest.approx(5/6)


def test_ce_body_close_not_wick_decides_weakening(triples):
    gap=detect_fvg(triples["bullish"],atr=10)
    wick=observe_fill(gap,candle(3,104,105,102,103),bar_idx=3)
    assert wick.fill_pct==pytest.approx(2/3) and wick.ce_status=="RESPECTED"
    body=observe_fill(gap,candle(4,103,104,102,102.25),bar_idx=4)
    assert body.ce_status=="WEAKENED" and not body.inversion_confirmed
    equality=observe_fill(gap,candle(5,103,104,102,102.5),bar_idx=5)
    assert equality.ce_status=="RESPECTED"


def test_wick_full_fill_is_not_body_invalidation(triples):
    gap=detect_fvg(triples["bullish"],atr=10)
    observation=observe_fill(gap,candle(3,104,106,100,104),bar_idx=3)
    assert observation.fill_pct==1 and observation.unfilled is None
    assert not observation.body_beyond_far_edge and not observation.inversion_confirmed
    equality=observe_fill(gap,candle(4,103,105,100,101),bar_idx=4)
    assert equality.fill_pct==1 and not equality.body_beyond_far_edge


def test_inversion_needs_both_full_trade_coverage_and_far_edge_close(triples):
    bull=detect_fvg(triples["bullish"],atr=10)
    bear=detect_fvg(triples["bearish"],atr=10)
    assert observe_fill(bull,candle(3,104,105,99,100),bar_idx=3).inversion_direction=="BEARISH"
    assert observe_fill(bear,candle(3,95,101,94,100),bar_idx=3).inversion_direction=="BULLISH"
    skipped=observe_fill(bull,candle(3,100,100.5,98,99),bar_idx=3)
    assert skipped.body_beyond_far_edge and not skipped.touched
    assert skipped.fill_pct==0 and not skipped.inversion_confirmed
    previously_full=observe_fill(bull,candle(4,100,100.5,98,99),bar_idx=4,previous_fill=1)
    assert previously_full.inversion_confirmed


def test_forming_wicks_are_display_observations_not_confirmed_lifecycle(triples):
    gap=detect_fvg(triples["bullish"],atr=10)
    original=gap.canonical_json()
    preview=observe_fill(gap,candle(3,104,105,99,100,complete=False),bar_idx=3)
    assert preview.fill_pct==1 and preview.ce_status=="PROVISIONAL"
    assert not preview.confirmed and not preview.inversion_confirmed and not preview.body_beyond_far_edge
    assert gap.canonical_json()==original


def test_fill_does_not_shrink_original_geometry_or_decrease(triples):
    gap=detect_fvg(triples["bullish"],atr=10)
    first=observe_fill(gap,candle(3,104,106,102,103),bar_idx=3)
    second=observe_fill(gap,candle(4,105,107,105,106),bar_idx=4,previous_fill=first.fill_pct)
    assert first.fill_pct==second.fill_pct
    assert (gap.price_lo,gap.price_hi,gap.ce)==(101,104,102.5)
    assert first.unfilled==second.unfilled


def test_creation_bar_cannot_fill_itself_and_bad_inputs_reject(triples):
    sample=triples["bullish"]
    gap=detect_fvg(sample,atr=10)
    with pytest.raises(ValueError,match="follow"):
        observe_fill(gap,sample[2],bar_idx=2)
    for fraction in (-.1,1.1,float("nan")):
        with pytest.raises(ValueError,match="fraction"):
            observe_fill(gap,candle(3,104,105,102,103),bar_idx=3,previous_fill=fraction)
    with pytest.raises(ValueError,match="exactly"):
        detect_fvg(sample[:2],atr=10)
    with pytest.raises(ValueError,match="ordered"):
        detect_fvg(sample[::-1],atr=10)


def test_approved_zone_config_persists_and_is_frozen():
    raw=yaml.safe_load((Path(__file__).parents[3]/"config/oracle.yaml").read_text(encoding="utf-8"))
    settings=ZonesConfig.model_validate(raw["zones"])
    assert settings.fvg_min_atr==.2 and settings.max_visible_per_tf.fvg==3
    assert settings.ob_boundary=="body_to_wick" and settings.htf_overlay==("H4","H1")
    with pytest.raises(ValidationError):
        settings.max_visible_per_tf.fvg=4


def test_all_5000_prefixes_match_full_history_at_the_same_creation_horizon():
    sample=[candle(i,1000+(i%9)*3,1001+(i%9)*3,999+(i%9)*3,1000.5+(i%9)*3)
            for i in range(5000)]
    full_atr=rma_atr(sample,14)
    found=0
    for i in range(2,len(sample)):
        prefix=sample[:i+1]
        expected=detect_fvg(sample[i-2:i+1],atr=full_atr[i],start_idx=i-2)
        actual=detect_fvg(prefix[-3:],atr=rma_atr(prefix,14)[-1],start_idx=i-2)
        assert actual==expected,f"FVG lookahead at bar {i}"
        if actual is not None:
            found+=1
            assert actual.created_idx==i
            assert actual.source_bars==(i-2,i-1,i)
    assert found>0


def test_creation_atr_is_frozen_despite_later_volatility(triples):
    gap = detect_fvg(triples["bullish"], atr=15)
    record = create_fvg_record(gap)
    before = gap.canonical_json()
    updated = advance_fvg(record, candle(3, 105, 106, 104.5, 105.5), bar_idx=3).record
    assert updated.geometry.atr_at_creation == 15
    assert updated.geometry.canonical_json() == before
    assert detect_fvg(triples["bullish"], atr=7.5).atr_at_creation == 7.5
    with pytest.raises(ValidationError):
        updated.geometry.atr_at_creation = 7.5
    with pytest.raises(ValidationError):
        FVGGeometry.model_validate(gap.model_dump() | {"schema_version": 1})


def test_ce_loss_is_latched_with_first_bar_provenance_and_stable_identity(triples):
    record = create_fvg_record(detect_fvg(triples["bullish"], atr=10))
    lost = advance_fvg(record, candle(3, 103, 104, 102, 102.25), bar_idx=3)
    assert lost.record.weakened and not lost.record.eligible_for_a_setup
    assert lost.record.weakened_at_ms == BASE+4*STEP
    assert lost.record.weakened_bar_index == 3
    assert [e.kind for e in lost.events] == ["CE_LOST"]
    reclaimed = advance_fvg(lost.record, candle(4, 103, 106, 102, 105), bar_idx=4)
    assert reclaimed.record.weakened and not reclaimed.record.eligible_for_a_setup
    assert reclaimed.record.weakened_bar_index == 3
    assert reclaimed.record.id == lost.record.id == record.id
    assert not reclaimed.events
    checkpoint = FVGRecord.model_validate_json(lost.record.canonical_json())
    assert advance_fvg(checkpoint, candle(4, 103, 106, 102, 105), bar_idx=4) == reclaimed


def test_ifvg_parent_link_terminal_original_and_depth_cap(triples):
    original = create_fvg_record(detect_fvg(triples["bullish"], atr=10))
    inverted = advance_fvg(original, candle(3, 104, 105, 99, 100), bar_idx=3)
    assert inverted.record.state == "INVERTED"
    assert not inverted.record.is_target and not inverted.record.renders
    child = inverted.child
    assert child.kind == "IFVG" and child.inversion_depth == 1
    assert child.parent_id == original.id and child.id != original.id
    assert child.geometry.direction == "BEARISH"
    assert child.geometry.atr_at_creation == original.geometry.atr_at_creation
    assert child.reason_chain == (f"inverted from FVG {original.id} on body close at 100.0",)
    failed = advance_fvg(child, candle(4, 103, 106, 102, 105), bar_idx=4)
    assert failed.record.state == "INVALID" and not failed.record.renders
    assert failed.child is None
    assert sum(e.kind == "REINVERSION_ATTEMPT" for e in failed.events) == 1
    again = advance_fvg(failed.record, candle(5, 103, 106, 102, 105), bar_idx=5)
    assert again.record == failed.record and again.child is None and not again.events
    assert advance_fvg(inverted.record, candle(4, 103, 106, 102, 105), bar_idx=4).record == inverted.record


def test_ifvg_depth_cap_and_latch_are_mirrored_for_bearish_origin(triples):
    original = create_fvg_record(detect_fvg(triples["bearish"], atr=10))
    lost = advance_fvg(original, candle(3, 97, 98.5, 96, 98), bar_idx=3).record
    assert lost.weakened
    reclaimed = advance_fvg(lost, candle(4, 97, 98, 94, 95), bar_idx=4).record
    assert reclaimed.weakened and reclaimed.weakened_bar_index == 3
    child = advance_fvg(reclaimed, candle(5, 98, 101, 97, 100), bar_idx=5).child
    assert child.geometry.direction == "BULLISH" and child.parent_id == original.id
    failed = advance_fvg(child, candle(6, 96, 98, 94, 95), bar_idx=6)
    assert failed.record.state == "INVALID" and failed.child is None


def test_forming_bars_cannot_commit_a_latch_or_lifecycle(triples):
    record = create_fvg_record(detect_fvg(triples["bullish"], atr=10))
    with pytest.raises(ValueError, match="forming"):
        advance_fvg(record, candle(3, 104, 105, 99, 100, complete=False), bar_idx=3)
    with pytest.raises(ValueError, match="confirmed"):
        advance_imbalance(ImbalanceCursor(), candle(0, 100, 101, 99, 100, complete=False))
    assert not record.weakened and record.state == "FRESH"


def test_incremental_creation_atr_and_checkpoint_replay_match_shared_atr():
    sample = [candle(i, 1000+(i%9)*3, 1001+(i%9)*3, 999+(i%9)*3, 1000.5+(i%9)*3)
              for i in range(100)]
    atr_values = rma_atr(sample, 14)
    cursor = ImbalanceCursor()
    snapshots = []
    for bar in sample:
        cursor = advance_imbalance(cursor, bar)
        snapshots.append(cursor)
    assert cursor.records
    for record in cursor.records:
        assert record.geometry.atr_at_creation == atr_values[record.geometry.created_idx]
    resumed = snapshots[49]
    for bar in sample[50:]:
        resumed = advance_imbalance(resumed, bar)
    assert resumed == cursor
    assert sum(e.kind == "REINVERSION_ATTEMPT" for e in resumed.events) == sum(
        e.kind == "REINVERSION_ATTEMPT" for e in cursor.events)


def merge_candidate(index, lo, hi, *, atr=10, direction="BULLISH", state="FRESH"):
    # Hand-built synthetic records isolate overlap geometry from the detector.
    if direction == "BULLISH":
        triple = [candle(index, lo-1, lo, lo-2, lo-1),
                  candle(index+1, lo, hi+1, lo, hi),
                  candle(index+2, hi+1, hi+2, hi, hi+1)]
    else:
        triple = [candle(index, hi+1, hi+2, hi, hi+1),
                  candle(index+1, hi, hi, lo-1, lo),
                  candle(index+2, lo-1, lo, lo-2, lo-1)]
    record = create_fvg_record(detect_fvg(triple, atr=atr, start_idx=index,
                                        config=ZonesConfig(fvg_min_atr=0)))
    return FVGRecord.model_validate(record.model_dump() | {"state": state})


def test_three_stacked_gaps_make_one_union_with_latest_creation_and_atr():
    records = [merge_candidate(0, 100, 104, atr=8), merge_candidate(1, 101, 105, atr=9),
               merge_candidate(2, 102, 106, atr=10)]
    plan = plan_fvg_merges(records)
    assert len(plan.components) == 1 and not plan.events
    union = build_fvg_union(plan.components[0])
    assert union.strength == 3
    assert (union.geometry.price_lo, union.geometry.price_hi, union.geometry.ce) == (100, 106, 103)
    assert union.geometry.created_ms == records[2].geometry.created_ms
    assert union.geometry.created_ms != records[0].geometry.created_ms
    assert union.geometry.t_start_ms == records[0].geometry.t_start_ms
    assert union.geometry.atr_at_creation == 10
    assert union.constituent_ids == tuple(sorted(r.id for r in records))
    assert union.id not in union.constituent_ids


def test_connected_component_merging_is_transitive_and_shuffle_independent():
    records = [merge_candidate(0, 100, 104), merge_candidate(1, 101.9, 105.9),
               merge_candidate(2, 103.8, 107.8)]
    # A/C overlap is only 0.2 / 4, while both adjacent edges exceed 0.5.
    expected_plan = plan_fvg_merges(records)
    assert len(expected_plan.components) == 1 and len(expected_plan.components[0]) == 3
    expected = build_fvg_union(expected_plan.components[0]).canonical_json()
    rng = random.Random(420)
    for _ in range(100):
        rng.shuffle(records)
        plan = plan_fvg_merges(records)
        assert plan == expected_plan
        assert build_fvg_union(plan.components[0]).canonical_json() == expected


def test_full_containment_merges_and_exact_overlap_threshold_does_not():
    contained = [merge_candidate(0, 100, 110), merge_candidate(1, 104, 104.3)]
    assert build_fvg_union(plan_fvg_merges(contained).components[0]).strength == 2
    touching_threshold = [merge_candidate(0, 100, 104), merge_candidate(1, 102, 106)]
    assert not plan_fvg_merges(touching_threshold).components


def test_inherited_weakening_is_latched_separately_from_union_ce_loss():
    a = merge_candidate(0, 100, 104)
    b = merge_candidate(1, 101, 105)
    a = FVGRecord.model_validate(a.model_dump() | {
        "weakened": True, "weakened_at_ms": BASE+4*STEP, "weakened_bar_index": 3})
    union = build_fvg_union(plan_fvg_merges([a, b]).components[0])
    assert union.weakened and union.weakened_at_ms == a.weakened_at_ms
    assert union.weakened_bar_index == 3 and not union.ce_lost
    assert not union.eligible_for_a_setup
    lost = advance_fvg(union, candle(4, 103, 104, 101, 102), bar_idx=4).record
    assert lost.weakened and lost.ce_lost and lost.ce_lost_bar_index == 4
    reclaimed = advance_fvg(lost, candle(5, 104, 106, 103, 105), bar_idx=5).record
    assert reclaimed.ce_lost and reclaimed.weakened
    assert reclaimed.weakened_at_ms == a.weakened_at_ms


def test_span_cap_rejects_whole_component_without_pairwise_fallback():
    records = [merge_candidate(0, 100, 104, atr=2), merge_candidate(1, 101.9, 105.9, atr=2),
               merge_candidate(2, 103.8, 107.8, atr=2)]
    plan = plan_fvg_merges(records)
    assert not plan.components
    assert len(plan.events) == 1 and plan.events[0].kind == "MERGE_REJECTED"
    assert all(r.state == "FRESH" and r.renders for r in records)
    at_cap = [merge_candidate(0, 100, 104, atr=2), merge_candidate(1, 101, 105, atr=2)]
    assert len(plan_fvg_merges(at_cap).components) == 1


def test_merge_requires_matching_state_direction_timeframe_and_live_fvg():
    a = merge_candidate(0, 100, 104)
    for state in ("TOUCHED", "MITIGATED", "FILLED", "INVERTED", "INVALID", "MERGED"):
        assert not plan_fvg_merges([a, merge_candidate(1, 101, 105, state=state)]).components
    assert not plan_fvg_merges([a, merge_candidate(1, 101, 105, direction="BEARISH")]).components
    other = merge_candidate(1, 101, 105)
    other = FVGRecord.model_validate(other.model_dump() | {
        "geometry": other.geometry.model_dump() | {"tf": "H1"}})
    assert not plan_fvg_merges([a, other]).components
    merged = FVGRecord.model_validate(a.model_dump() | {"state": "MERGED"})
    assert not merged.renders and not merged.is_target
    assert advance_fvg(merged, candle(3, 104, 105, 99, 100), bar_idx=3).record == merged


def stacked_history():
    return [candle(0, 99, 100, 98, 99.5), candle(1, 100, 101, 99, 100.5),
            candle(2, 104, 104.1, 104, 104.05), candle(3, 107, 108, 107, 107.5),
            candle(4, 108, 110, 108, 109)]


def test_committed_union_preserves_constituents_and_excludes_formation_candles_from_union_fill():
    bars = stacked_history()
    records = [create_fvg_record(detect_fvg(bars[i:i+3], atr=10, start_idx=i)) for i in range(3)]
    original = [r.canonical_json() for r in records]
    horizon = bars[-1].t_open_ms+STEP
    result = merge_fvgs(records, bars, as_of_ms=horizon)
    union = next(r for r in result.records if r.constituent_ids)
    assert union.strength == 3 and union.geometry.ce == 104
    assert union.geometry.created_ms == horizon
    assert union.fill_pct == 0  # Formation candles cannot fill a newly confirmed union.
    assert all(r.state == "MERGED" and not r.renders and not r.is_target
               for r in result.records if not r.constituent_ids)
    assert [r.canonical_json() for r in records] == original
    assert [e.kind for e in result.events] == ["MERGED"]
    rng = random.Random(101)
    expected = result.canonical_json()
    for _ in range(100):
        rng.shuffle(records)
        assert merge_fvgs(records, bars, as_of_ms=horizon).canonical_json() == expected
    again = merge_fvgs(result.records, bars, as_of_ms=horizon)
    assert again.records == result.records and not again.events


def test_union_replay_horizon_excludes_future_bars_and_latches_its_own_ce():
    bars = stacked_history()
    records = [create_fvg_record(detect_fvg(bars[i:i+3], atr=10, start_idx=i)) for i in range(3)]
    future = [candle(5, 106, 107, 102, 103), candle(6, 105, 110, 104.5, 109)]
    at_creation = merge_fvgs(records, bars, as_of_ms=BASE+5*STEP)
    assert merge_fvgs(records, bars+future, as_of_ms=BASE+5*STEP) == at_creation
    later = merge_fvgs(records, bars+future, as_of_ms=BASE+7*STEP)
    union = next(r for r in later.records if r.constituent_ids)
    assert union.fill_pct == .75
    assert union.ce_lost and union.ce_lost_bar_index == 5
    assert union.ce_lost_at_ms == BASE+6*STEP
    assert not union.weakened and not union.eligible_for_a_setup
    assert union.geometry == next(r for r in at_creation.records if r.constituent_ids).geometry
    checkpoint = next(r for r in at_creation.records if r.constituent_ids)
    for index, bar in enumerate(future, start=5):
        checkpoint = advance_fvg(checkpoint, bar, bar_idx=index).record
    assert checkpoint == union


def test_merge_rejection_keeps_all_original_records_visible_and_logs_once():
    bars = stacked_history()
    records = [create_fvg_record(detect_fvg(bars[i:i+3], atr=10, start_idx=i)) for i in range(3)]
    result = merge_fvgs(records, bars, as_of_ms=BASE+5*STEP,
                        config=ZonesConfig(max_merged_span_atr=.5))
    assert set(r.id for r in result.records) == set(r.id for r in records)
    assert all(r.state == "FRESH" and r.renders for r in result.records)
    assert len(result.events) == 1 and result.events[0].kind == "MERGE_REJECTED"


def test_detection_cursor_commits_merges_and_replay_from_checkpoint_is_identical():
    bars = [candle(i, 95, 96, 94, 95) for i in range(14)]
    bars += [Bar.model_validate(bar.model_dump() | {
        "t_open_ms": bar.t_open_ms+14*STEP, "id": "", "object_hash": ""}) for bar in stacked_history()]
    cursor = ImbalanceCursor()
    for bar in bars[:16]:
        cursor = advance_imbalance(cursor, bar)
    checkpoint = cursor
    for bar in bars[16:]:
        cursor = advance_imbalance(cursor, bar)
    assert any(event.kind == "MERGED" for event in cursor.events)
    assert any(record.state == "MERGED" for record in cursor.records)
    resumed = checkpoint
    for bar in bars[16:]:
        resumed = advance_imbalance(resumed, bar)
    assert resumed == cursor
    assert checkpoint.next_index == 16 and len(checkpoint.stored_bars) == 16
