"""Small synthetic unit fixtures; the later producer golden must use broker history."""

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from oracle.indicators.ut_bot import ATRState, rma_atr
from oracle.models import Bar
from oracle.smc.swings import SwingConfig, advance_swings, load_swing_config, swing_stream, swings


def bars(highs, lows=None, *, complete=True):
    lows = lows if lows is not None else [90.0] * len(highs)
    return [Bar(tf="M15", t_open_ms=1700000100000 + i * 900000,
                o=(hi + lo) / 2, c=(hi + lo) / 2, h=hi, l=lo,
                source="synthetic", tick_volume=10, complete=complete)
            for i, (hi, lo) in enumerate(zip(highs, lows, strict=True))]


def config(threshold=1.0, *, period=1):
    return SwingConfig(atr_period=period, significance_atr={"default": threshold})


def test_five_bar_textbook_high_and_low_use_wicks():
    high = swings(bars([101, 102, 105, 102, 101]), config())
    low = swings(bars([110] * 5, [100, 99, 95, 99, 100]), config())
    assert [(p.side, p.idx, p.price) for p in high.internal] == [("HIGH", 2, 105)]
    assert [(p.side, p.idx, p.price) for p in low.internal] == [("LOW", 2, 95)]


def test_textbook_fractals_labels_and_provenance():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/synthetic/swings_textbook.json").read_text())
    sample = bars(fixture["highs"], fixture["lows"])
    result = swings(sample, config(0.1))
    highs = [p for p in result.internal if p.side == "HIGH"]
    lows = [p for p in result.internal if p.side == "LOW"]
    assert [p.idx for p in highs] == fixture["confirmed_high_indices"]
    assert [p.idx for p in lows] == fixture["confirmed_low_indices"]
    assert [p.kind for p in highs] == [None, "HH", "LH"]
    assert [p.kind for p in lows] == [None, "LL"]
    assert highs[0].opposite_pivot_id is None
    assert highs[0].significant is False
    for pivot in result.internal:
        assert pivot.source_bars == tuple(range(pivot.idx - 2, pivot.idx + 3))
        assert pivot.source_object_ids == tuple(sample[i].id for i in pivot.source_bars)
        assert pivot.confirmed_at_idx == pivot.idx + 2
        assert pivot.confirmed_at_ms == sample[pivot.idx + 2].t_open_ms + 900000
    with pytest.raises(ValidationError):
        highs[0].price = 200


def test_flat_top_and_bottom_elect_first_bar_only():
    sample = bars([100, 101, 105, 105, 105, 102, 101], [99, 98, 95, 95, 95, 97, 98])
    result = swings(sample, config())
    assert [(p.side, p.idx) for p in result.internal] == [("HIGH", 2), ("LOW", 2)]


def test_equal_high_pool_grows_without_losing_members_or_old_snapshot():
    sample = bars([100, 101, 105, 101, 100, 101, 105.05, 101, 100, 101, 105.04, 101, 100])
    first = swings(sample[:5], config())
    second = swings(sample[:9], config())
    third = swings(sample, config())
    assert first.equal_pairs == ()
    assert second.equal_pairs[0].count == 2
    assert third.equal_pairs[0].count == 3
    pair = third.equal_pairs[0]
    assert pair.kind == "EQH"
    assert pair.bar_indices == (2, 6, 10)
    assert pair.pivot_ids == tuple(p.id for p in third.internal)
    assert pair.price_mean == pytest.approx((105 + 105.05 + 105.04) / 3)
    assert all(p.kind is None for p in third.internal)
    assert second.equal_pairs[0].count == 2  # later pool expansion cannot rewrite history


def test_equal_low_pool_and_tolerance_boundary():
    sample = bars([110] * 9, [101, 100, 95, 100, 101, 100, 95.1, 100, 101])
    result = swings(sample, config())
    assert result.equal_pairs[0].kind == "EQL"
    assert result.equal_pairs[0].count == 2


def test_equal_tolerance_is_inclusive_and_outside_it_remains_classified():
    highs = [100, 100.1, 100.5, 100.1, 100, 100.1, 100.6, 100.1, 100,
             100.1, 100.8, 100.1, 100]
    sample = bars(highs, [h - 1 for h in highs])
    result = swings(sample, config(0.01))
    highs = [p for p in result.internal if p.side == "HIGH"]
    assert highs[1].kind is None
    assert highs[2].kind == "HH"
    assert result.equal_pairs[0].count == 2
    assert result.equal_pairs[0].tolerance == pytest.approx(0.1)


def test_failed_significance_is_internal_and_never_major():
    sample = bars([101, 103, 106, 103, 101, 102, 104, 107, 103, 101],
                  [99, 100, 101, 99, 96, 98, 100, 101, 99, 95])
    result = swings(sample, config(100))
    assert result.internal
    assert result.major == ()
    assert all(not p.significant for p in result.internal)


def test_alternation_demotes_lower_consecutive_high_and_preserves_internal():
    sample = bars([101, 103, 106, 103, 101, 102, 104, 107, 103, 101, 102, 104, 110, 103, 101],
                  [99, 100, 101, 99, 96, 98, 99, 100, 99, 99, 99, 99, 99, 99, 99])
    result = swings(sample, config(0.1))
    assert [p.idx for p in result.major] == [4, 12]
    assert {7, 12} <= {p.idx for p in result.internal}
    assert all(a.side != b.side for a, b in zip(result.major, result.major[1:]))
    assert result.internal[-1].leg_atr == pytest.approx((110 - 96) / (110 - 99))


def test_low_alternation_keeps_lower_and_rejects_higher():
    sample = bars([104, 105, 108, 105, 104, 103, 103, 103, 103, 103, 103, 103, 103, 103, 103],
                  [99, 98, 100, 98, 95, 98, 99, 96, 99, 98, 99, 98, 94, 98, 99])
    result = swings(sample, config(0.1))
    assert [p.idx for p in result.major] == [12]
    assert {4, 7, 12} <= {p.idx for p in result.internal if p.side == "LOW"}


def test_provisional_id_is_stable_confirmation_waits_for_closed_right_bars():
    sample = bars([100, 101, 105, 101, 100])
    provisional = swings(sample[:3], config()).provisional[0]
    assert not provisional.confirmed
    assert swings(sample[:3], config()).structure_inputs == ()
    assert swings(sample[:3], config()).call_inputs == ()
    assert swings(sample[:4], config()).internal == ()
    forming = Bar.model_validate(sample[-1].model_dump() | {"complete": False, "id": "", "object_hash": ""})
    still_waiting = swings([*sample[:-1], forming], config())
    assert still_waiting.internal == ()
    assert still_waiting.atr[-1] is None
    assert any(p.id == provisional.id and not p.confirmed for p in still_waiting.provisional)
    confirmed = swings(sample, config()).internal[0]
    assert confirmed.id == provisional.id
    assert confirmed.confirmed


def test_gap_adjacent_pivot_is_flagged_not_dropped():
    sample = bars([100, 101, 105, 101, 100])
    sample = [Bar.model_validate(b.model_dump() | {"t_open_ms": b.t_open_ms + (172800000 if i >= 2 else 0),
                                                  "id": "", "object_hash": ""}) for i, b in enumerate(sample)]
    pivot = swings(sample, config()).internal[0]
    assert pivot.gap_adjacent and pivot.idx == 2


def test_incremental_atr_is_byte_identical_to_existing_batch_and_preserves_carry():
    sample = bars([100 + (i % 7) for i in range(100)])
    carry = ATRState(14)
    actual = []
    for bar in sample:
        prior = carry
        values, carry = rma_atr((bar,), 14, state=carry, with_state=True)
        assert prior.count + 1 == carry.count
        actual.extend(values)
    assert actual == rma_atr(sample, 14)
    assert swings(sample).atr == tuple(actual)
    assert carry.count == 100
    with pytest.raises(ValueError, match="period"):
        rma_atr(sample, 10, state=carry)


def test_pure_incremental_cursor_matches_batch_and_replaces_forming_candle():
    sample = bars([100, 101, 105, 101, 100, 101, 106, 102, 101])
    cursor = None
    settings = config()
    for i, bar in enumerate(sample):
        prior = cursor
        cursor = advance_swings(cursor, bar, settings)
        assert cursor.snapshot == swings(sample[:i + 1], settings)
        if prior is not None:
            assert len(prior.bars) == i
    with pytest.raises(ValueError, match="parameters changed"):
        advance_swings(cursor, sample[-1], config(2))
    waiting = None
    for bar in sample[:4]:
        waiting = advance_swings(waiting, bar, settings)
    forming = Bar.model_validate(sample[4].model_dump() | {"complete": False, "id": "", "object_hash": ""})
    waiting = advance_swings(waiting, forming, settings)
    assert waiting.snapshot.internal == ()
    closed = advance_swings(waiting, sample[4], settings)
    assert closed.snapshot == swings(sample[:5], settings)
    assert waiting.snapshot.internal == ()
    assert closed.atr_state.count == 5


def test_atr_significance_uses_pivot_bar_not_future_confirmation_volatility():
    sample = bars([101, 103, 106, 103, 101, 102, 104, 107, 103, 101],
                  [99, 100, 101, 99, 96, 98, 100, 101, 99, 95])
    pivot = next(p for p in swings(sample, config()).internal if p.idx == 7)
    assert pivot.atr == 6
    assert pivot.leg_atr == pytest.approx(11 / 6)


def test_config_reads_weights_per_timeframe_and_rejects_invalid_thresholds():
    settings = load_swing_config(Path(__file__).parents[3] / "config/weights.yaml")
    assert settings.threshold("M1") == 1.4
    assert settings.threshold("H4") == 0.7
    assert settings.threshold("W1") == 1.0
    with pytest.raises(ValidationError):
        settings.significance_atr.M1 = 5
    for values in ({}, {"default": 0}, {"default": -1}, {"default": float("nan")}, {"default": 1, "typo": 2}):
        with pytest.raises(ValidationError):
            SwingConfig(significance_atr=values)


def test_input_rejects_mixed_timeframes_duplicates_and_nonterminal_forming_bar():
    sample = bars([100, 101, 105, 101, 100])
    with pytest.raises(ValueError, match="ordered"):
        swings([sample[0], sample[0]])
    other = Bar.model_validate(sample[1].model_dump() | {"tf": "M1", "id": "", "object_hash": ""})
    with pytest.raises(ValueError, match="timeframe"):
        swings([sample[0], other])
    forming = Bar.model_validate(sample[0].model_dump() | {"complete": False, "id": "", "object_hash": ""})
    with pytest.raises(ValueError, match="forming"):
        swings([forming, sample[1]])
    assert swings([]).internal == ()


def test_all_5000_prefixes_match_causal_full_stream_without_lookahead():
    sample = bars([110 + 8 * math.sin(i / 17) + math.sin(i / 7) for i in range(5000)],
                  [90 + 8 * math.sin(i / 17) + math.sin(i / 7) for i in range(5000)])
    full = swing_stream(sample)
    for i, expected in enumerate(full):
        assert swings(sample[:i + 1]) == expected, f"lookahead at bar {i}"
        assert all(p.confirmed_at_idx <= i for p in expected.internal)
        assert all(p.idx + 2 <= i for p in expected.internal)
        assert all(not p.confirmed for p in expected.provisional)
