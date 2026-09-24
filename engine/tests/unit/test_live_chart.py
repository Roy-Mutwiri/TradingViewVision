from types import SimpleNamespace
from unittest.mock import patch

import pytest

from oracle.config import ChartConfig, DataConfig, OracleConfig
from oracle.data.broker_bar import RawBrokerBar
from oracle.data.broker_clock import BrokerClock
from oracle.data.calendar import Closure, TradingCalendar
from oracle.data.candle_store import CandleStore
from oracle.data.instrument import Instrument
from oracle.data.live_chart import LiveChart
from oracle.data.mt5_feed import MT5Feed
from oracle.data.symbol_policy import assert_gold_symbol
from oracle.models import Bar, timeframe_ms
from oracle.transport.chart import BarUpdate, ChartFrame
from oracle.transport.errors import EngineError

NOW = 1789684942000


class Terminal:
    TIMEFRAME_M1 = "M1"
    COPY_TICKS_ALL = 0

    def __init__(self):
        self.calls = []
        self.ticks = []

    def __getattr__(self, name):
        if name.startswith("TIMEFRAME_"):
            return name.removeprefix("TIMEFRAME_")
        raise AttributeError(name)

    def copy_rates_from_pos(self, symbol, tf, pos, count):
        self.calls.append((symbol, tf, pos, count))
        count = min(count, 300)
        step = timeframe_ms(tf)
        last = NOW // step * step
        return [
            dict(
                time=(last - (count - i - 1) * step) // 1000,
                open=4351.22,
                high=4353.8,
                low=4350.11,
                close=4352.64,
                tick_volume=417,
            )
            for i in range(count)
        ]

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time_msc=NOW, time=NOW // 1000, bid=4352.64, ask=4352.78)

    def copy_ticks_from(self, *args):
        return self.ticks


@pytest.fixture
def chart(tmp_path):
    api = Terminal()
    store = CandleStore(":memory:", "exness")
    config = OracleConfig(
        chart=ChartConfig(visible_bars=50, lookback=10),
        data=DataConfig(broker_clock_path=str(tmp_path / "broker-clock.json")),
    )
    feed = MT5Feed(api, config.data, store=store, allow_unproven=True)
    feed.broker_symbol = "XAUUSDz"
    feed.instrument = Instrument.from_mt5(
        SimpleNamespace(digits=2, point=0.01, trade_tick_size=0.01, trade_contract_size=100)
    )
    feed.clock = BrokerClock(
        broker="exness", transitions=((0, 0),), version=1, derivation="manual_override"
    )
    store.expect_clock(feed.clock)
    live = LiveChart(SimpleNamespace(status=lambda: None, feed=feed, config=config))
    live.now = lambda: NOW
    yield live, api, store
    store.close()


def test_snapshot_counts_and_timeframe_seams(chart):
    live, api, _ = chart
    for tf in ["M1", "H1", "M5"]:
        frame = live.subscribe(tf)
        assert len(frame.snapshot.bars) == (11 if tf == "M5" else 60)
        assert [b.t_open_ms for b in frame.snapshot.bars] == sorted(
            {b.t_open_ms for b in frame.snapshot.bars}
        )
        assert frame.next_close_ms == frame.snapshot.bars[-1].t_open_ms + timeframe_ms(tf)
        assert frame.snapshot.bars[-1].complete is (tf == "M5")
        if tf == "M5":
            assert not any(call[1] == "M5" for call in api.calls)
        else:
            assert any(call == ("XAUUSDz", tf, 0, 60) for call in api.calls)
        assert "t_broker_ms" not in frame.canonical_json()
    assert live.debug().resolved_symbol == "XAUUSDz"


def test_tick_batch_throttle_and_duplicate_millisecond_cursor(chart):
    live, api, _ = chart
    live.subscribe("M1")
    api.ticks = [
        dict(time_msc=NOW, bid=4352.64, ask=4352.78),
        dict(time_msc=NOW + 1, bid=4352.70, ask=4352.84),
        dict(time_msc=NOW + 1, bid=4352.71, ask=4352.85),
    ]
    with patch("oracle.data.live_chart.time.monotonic", return_value=10):
        frames = live.poll()
        assert live.builder.current.tick_volume == 419
        assert frames[-1].update.bar.c == 4352.71
        assert live.poll() == []
    with patch("oracle.data.live_chart.time.monotonic", return_value=10.2):
        live.poll()
        assert live.builder.current.tick_volume == 419


def test_broker_correction_is_published_and_archived(chart):
    live, _, store = chart
    live.subscribe("M1")
    t = NOW // 60000 * 60000 - 60000
    built = Bar(
        tf="M1",
        t_open_ms=t,
        o=4351.22,
        h=4353.80,
        l=4350.11,
        c=4352.50,
        tick_volume=400,
        source="mt5",
        complete=True,
    )
    live.closed_pending[t] = built
    with patch("oracle.data.live_chart.time.monotonic", return_value=10):
        frames = live.poll()
    correction = next(f for f in frames if f.kind == "correction")
    assert correction.update.bar.c == 4352.64
    assert live.debug().corrections == 1
    assert store.read("M1", t, t + 60000)[0].c == 4352.64


def test_maintenance_closure_suppresses_staleness(chart):
    live, _, _ = chart
    live.subscribe("M1")
    live.calendar = TradingCalendar(
        valid_from_ms=NOW - 86400000,
        valid_to_ms=NOW + 86400000,
        closures=(Closure(start_ms=NOW - 60000, end_ms=NOW + 3600000, recurring=True),),
    )
    live.calendar_pending = False
    live.last_tick_ms = NOW - 300000
    assert live.quality().state == "OK"
    assert live.quality().detail == "data.closed"
    live.calendar = None
    assert live.quality().state == "STALE"
    live.last_tick_ms = NOW
    live.spread = 201
    assert live.quality().state == "WIDE_SPREAD"


def test_fresh_measured_clock_serves_assumed_history(chart):
    live, _, store = chart
    live.feed.clock = BrokerClock(
        broker="exness", transitions=((NOW, 0),), version=1, derivation="measured"
    )
    frame = live.subscribe("M5")
    assert len(frame.snapshot.bars) == 60
    assert all(b.clock_confidence == "ASSUMED" for b in frame.snapshot.bars)
    assert frame.resolved_symbol == "XAUUSDz"
    assert len(store.raw_history("M5")) == 60
    assert len(store.read("M5", 0, NOW)) == 60


def test_continuous_gold_is_denied_before_selection():
    for symbol in ["XAUUSD247z", "xauusd247Z"]:
        with pytest.raises(EngineError, match="24/7"):
            assert_gold_symbol(symbol)
    assert_gold_symbol("XAUUSDz")


def test_no_bars_is_no_data_and_empty_history_is_typed(chart):
    live, api, _ = chart
    assert live.quality().state == "NO_DATA"
    api.copy_rates_from_pos = lambda *args: []
    with pytest.raises(EngineError) as failure:
        live.subscribe("M5")
    assert failure.value.wire()["code"] == "HISTORY_EMPTY"
    assert live.quality().state == "NO_DATA"


def test_symbol_error_lists_candidates_and_refinement_refetches(chart):
    live, _, _ = chart
    live.feed.broker_symbol = ""
    with pytest.raises(EngineError) as failure:
        live.subscribe("M5")
    assert failure.value.wire()["code"] == "SYMBOL_UNRESOLVED"
    assert "XAUUSDz" in failure.value.wire()["detail"]["candidates"]
    live.feed.broker_symbol = "XAUUSDz"
    live.subscribe("M5")
    refined = live.feed.clock.model_copy(update={"version": 2})
    packet = live.refine(refined)
    assert packet.kind == "clock_refined" and packet.snapshot.clockVersion == 2
    assert len(packet.snapshot.bars) == 60


def test_wire_rounds_only_at_serialization_boundary(chart):
    live, _, _ = chart
    live.subscribe("M1")
    bar = live.builder.current.transition(c=4352.64000001)
    frame = ChartFrame(
        kind="update",
        update=BarUpdate(tf="M1", bar=bar),
        quality=live.quality(),
        now_ms=NOW,
        bar_duration_ms=60000,
    )
    assert frame.wire()["update"]["bar"]["c"] == 4352.64
    assert bar.c == 4352.64000001


def test_warm_switch_reads_store_without_broker_and_is_instrumented(chart):
    live, api, _ = chart
    live.subscribe("M5")
    api.calls.clear()
    frame = live.subscribe("M5")
    assert len(frame.snapshot.bars) == 60
    assert not api.calls
    assert 0 < live.debug().switch_ms < 150


def test_pending_weekend_is_not_a_gap_but_mid_session_hole_is(chart):
    from datetime import UTC, datetime

    live, _, _ = chart
    live.subscribe("M5")
    friday = int(datetime(2026, 9, 11, 21, tzinfo=UTC).timestamp()) * 1000
    sunday = int(datetime(2026, 9, 13, 22, tzinfo=UTC).timestamp()) * 1000
    template = next(iter(live.bars.values()))

    def at(t):
        return Bar.model_validate(
            template.model_dump(exclude={"id", "object_hash"}) | {"t_open_ms": t, "complete": True}
        )

    live.bars = {friday - 300000: at(friday - 300000), sunday: at(sunday)}
    assert live.quality().state == "CALENDAR_PENDING"
    assert not live.debug().missing_ranges
    monday = int(datetime(2026, 9, 14, 12, tzinfo=UTC).timestamp()) * 1000
    live.bars = {monday: at(monday), monday + 900000: at(monday + 900000)}
    assert live.quality().state == "GAPPED"
    assert live.debug().missing_ranges == [{"from_ms": monday + 300000, "to_ms": monday + 900000}]


def test_provisional_removal_and_confirmation_are_counted_without_withdrawing_closed_label(chart):
    live, _, _ = chart
    start = NOW // 300000 * 300000 - 36 * 300000

    def at(i, c, complete=True):
        return Bar(
            tf="M5",
            t_open_ms=start + i * 300000,
            o=c,
            h=c + 1,
            l=c - 1,
            c=c,
            tick_volume=100,
            source="synthetic",
            complete=complete,
        )

    bars = [at(i, 100 + i) for i in range(35)]
    bars.append(at(35, 80, False))
    live.bars = {b.t_open_ms: b for b in bars}
    preview = live._indicator_objects()
    assert len(preview) == 1 and not preview[0].confirmed
    assert preview[0].style.token == "utbot.provisional"
    live.bars[bars[-1].t_open_ms] = at(35, 136, False)
    assert not live._indicator_objects()
    assert live.indicator_detail["removed"] == 1
    live.bars[bars[-1].t_open_ms] = at(35, 80, False)
    live._indicator_objects()
    live.bars[bars[-1].t_open_ms] = at(35, 80)
    closed = live._indicator_objects()
    assert closed[0].id == preview[0].id and closed[0].confirmed
    assert live.indicator_detail["confirmed"] == 1
    assert live.indicator_detail["conversion_rate"] == 0.5
    live.bars[start + 36 * 300000] = at(36, 160, False)
    assert any(o.id == closed[0].id and o.confirmed for o in live._indicator_objects())


def test_stop_path_and_bar_colours_are_opt_in_even_without_labels(chart):
    live, _, _ = chart
    start = NOW // 300000 * 300000 - 40 * 300000
    bars = [
        Bar(
            tf="M5",
            t_open_ms=start + i * 300000,
            o=100 + i,
            h=101 + i,
            l=99 + i,
            c=100 + i,
            tick_volume=100,
            source="synthetic",
            complete=True,
        )
        for i in range(40)
    ]
    live.bars = {b.t_open_ms: b for b in bars}
    assert not live._indicator_objects()
    assert live.indicator_detail["bar_colors"] == []
    frame = live.set_indicator({"show_stop_line": True, "color_bars": True})
    assert len(frame.objects) == 1 and frame.objects[0].shape == "PATH"
    assert frame.objects[0].style.token == "utbot.stop"
    assert len(frame.bar_colors) == 10


def test_bulk_projection_rejects_collision_without_overwriting(chart):
    _, _, store = chart
    raw = RawBrokerBar(
        tf="M1",
        t_broker_ms=NOW // 60000 * 60000,
        o=1,
        h=2,
        l=1,
        c=2,
        tick_volume=1,
        digits=2,
        complete=True,
    )
    clock = BrokerClock(
        broker="exness", transitions=((0, 0),), version=1, derivation="manual_override"
    )
    store.put_broker_many([raw.normalize(clock)])
    shifted = RawBrokerBar.model_validate(
        raw.model_dump() | {"t_broker_ms": raw.t_broker_ms + 3600000}
    )
    other = BrokerClock(
        broker="exness", transitions=((0, 3600),), version=1, derivation="manual_override"
    )
    with pytest.raises(ValueError, match="collapse"):
        store.put_broker_many([shifted.normalize(other)])
    assert len(store.raw_history("M1")) == 2
    assert store.read("M1", 0, NOW + 60000)[0].t_open_ms == raw.t_broker_ms
