import json
from dataclasses import asdict
from pathlib import Path

import pytest

from oracle.config import UTBotConfig
from oracle.indicators.parity import ReferenceLabels, verify_oanda_labels
from oracle.indicators.ut_bot import draw_ut_bot, rma_atr, ut_bot
from oracle.models import Bar


def bar(i, price, high=None, low=None, complete=True):
    return Bar(
        tf="M15",
        t_open_ms=1700000100000 + i * 900000,
        o=price,
        c=price,
        h=high if high is not None else price + 1,
        l=low if low is not None else price - 1,
        tick_volume=100,
        source="synthetic",
        complete=complete,
    )


def test_hand_computed_wilder_atr_on_30_fixed_bars():
    bars = [bar(i, 100 + i, high=100 + i + (i % 3 + 1), low=99 + i) for i in range(30)]
    # TR repeats 2,3,4. SMA seed is 2.9, followed by hand-calculated Wilder steps.
    expected = [
        2.9,
        2.91,
        3.019,
        2.9171,
        2.92539,
        3.032851,
        2.9295659,
        2.93660931,
        3.042948379,
        2.9386535411,
        2.94478818699,
        3.050309368291,
        2.9452784314619,
        2.95075058831571,
        3.055675529484139,
        2.950107976535725,
        2.955097178882153,
        3.059587460993937,
        2.953628714894543,
        2.958265843405089,
        3.06243925906458,
    ]
    actual = rma_atr(bars, 10)
    assert actual[:9] == [None] * 9
    assert actual[9:] == pytest.approx(expected, abs=1e-9, rel=0)


def test_frozen_2000_bar_math_golden():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/utbot_m15_math.json").read_text())
    bars = [Bar.model_validate(b) for b in fixture["bars"]]
    assert len(bars) == 2000
    assert [asdict(v) for v in ut_bot(bars)] == fixture["series"]
    assert [asdict(v) for v in ut_bot(bars)] == fixture["series"]


def test_no_early_signals_and_no_confirmed_withdrawals_during_tick_replay():
    bars = [bar(i, 100 + (i % 8 if i % 16 < 8 else 16 - i % 16) * 3) for i in range(80)]
    values = ut_bot(bars)
    assert not any(v.buy or v.sell for v in values[:30])
    confirmed = {}
    for i in range(len(bars)):
        for price in [bars[i].c + 4, bars[i].c - 4, bars[i].c]:
            forming = bar(i, price, complete=False)
            series = ut_bot(bars[:i] + [forming])
            assert not series[-1].buy and not series[-1].sell
            for j, prior in confirmed.items():
                assert series[j] == prior
        closed = ut_bot(bars[: i + 1])
        if closed[-1].buy or closed[-1].sell:
            confirmed[i] = closed[-1]
    assert confirmed
    objects = draw_ut_bot(bars, UTBotConfig(label_budget=2))
    assert len(objects) == 2
    assert all(o.confirmed and not o.warmup for o in objects)


def test_same_feed_parity_compares_fixed_labels_and_rejects_other_sources():
    bars = [
        bar(i, p).transition(source="twelve_data")
        for i, p in enumerate([100, 103, 106, 109, 90, 87, 110, 80])
    ]
    reference = ReferenceLabels(
        feed="OANDA:XAUUSD", atr_period=2, buy=[bars[6].t_open_ms], sell=[bars[7].t_open_ms]
    )
    assert verify_oanda_labels(bars, reference)["matched"]
    wrong = reference.model_copy(update={"buy": []})
    with pytest.raises(ValueError, match="label mismatch"):
        verify_oanda_labels(bars, wrong)
    with pytest.raises(ValueError, match="vendor-origin"):
        verify_oanda_labels([bar(i, b.c) for i, b in enumerate(bars)], reference)


def test_heikin_close_and_per_timeframe_defaults():
    assert UTBotConfig().for_tf("M1").enabled is False
    assert UTBotConfig().for_tf("H1").key == 2
    bars = [bar(i, 100 + i, high=105 + i, low=98 + i) for i in range(40)]
    result = ut_bot(bars, heikin=True)
    assert result[9].stop == pytest.approx((bars[9].o + bars[9].h + bars[9].l + bars[9].c) / 4 - 7)
