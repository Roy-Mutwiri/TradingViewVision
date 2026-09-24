from datetime import UTC, datetime
from pathlib import Path
from random import Random
from types import SimpleNamespace

import pytest

from oracle.config import DataConfig, SessionsConfig, load_config
from oracle.data.analytical_days import analytical_levels, trading_day_bounds, trading_week_bounds
from oracle.data.broker_bar import RawBrokerBar
from oracle.data.broker_clock import (
    BoundaryEvidence,
    BrokerClock,
    derive_offset,
    derive_transitions,
)
from oracle.data.candle_store import CandleStore
from oracle.data.clock_alignment import assert_alignment, correlate_offsets
from oracle.data.clock_derivation import derive_history_clock
from oracle.data.clock_proof import require_seasonal_proof
from oracle.data.golden_source import write_golden
from oracle.data.mt5_feed import MT5Feed
from oracle.models import Bar
from oracle.replay.golden import read_golden
from oracle.transport.protocol import export_schema


def epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp()) * 1000


def raw_bar(t: int, price: float = 2000) -> RawBrokerBar:
    return RawBrokerBar(
        tf="M1",
        t_broker_ms=t,
        o=price,
        h=price + 0.5,
        l=price - 0.5,
        c=price + 0.1,
        tick_volume=3,
        digits=2,
        complete=True,
    )


def clock(offset: int = 0, version: int = 1) -> BrokerClock:
    return BrokerClock(
        broker="exness",
        server="ExnessKE-MT5Trial10",
        transitions=((0, offset),),
        version=version,
        derivation="manual_override",
    )


def price_window(start: int, offset: int) -> tuple[list[RawBrokerBar], list[Bar]]:
    rng = Random(start)
    price = 2000.0
    vendor = []
    for i in range(2200):
        price += rng.uniform(-2, 2)
        vendor.append(
            Bar(
                tf="M1",
                t_open_ms=start + i * 60000,
                o=price,
                h=price + 0.5,
                l=price - 0.5,
                c=price + 0.1,
                tick_volume=0,
                source="twelve_data",
                complete=True,
            )
        )
    raw = [
        RawBrokerBar.model_validate(
            b.model_dump(
                exclude={"id", "object_hash", "symbol", "source", "t_open_ms", "clock_confidence"}
            )
            | {"t_broker_ms": b.t_open_ms + offset * 1000}
        )
        for b in vendor[700:1200]
    ]
    return raw, vendor


@pytest.mark.parametrize("offset", [0, 3600, 7200, 10800, -18000])
def test_live_offset_allowlist(offset: int) -> None:
    assert derive_offset(100000 + offset + 60, 100000) == offset


def test_exness_expected_offsets_and_pin() -> None:
    config = load_config(Path(__file__).resolve().parents[3] / "config/oracle.yaml")
    assert config.data.canonical_broker == "exness"
    assert config.data.broker_symbol_patterns == ("XAUUSD", "XAUUSDm", "XAUUSDc", "XAUUSDz")
    with pytest.raises(ValueError, match="outside canonical"):
        clock(7200).assert_expected("exness", config.data.expected_offset_s)


def test_october_transition_is_effective_dated_not_current_constant() -> None:
    before = epoch("2025-10-24T21:00")
    after = epoch("2025-10-26T23:00")
    derived = derive_transitions(
        "fixture-eet",
        (
            BoundaryEvidence(t_broker_ms=before, t_utc_ms=before - 10800000),
            BoundaryEvidence(t_broker_ms=after, t_utc_ms=after - 7200000),
        ),
    )
    assert derived.offset_ms_at(before) == 10800000
    assert derived.offset_ms_at(after - 1) == 10800000
    assert derived.offset_ms_at(after) == 7200000
    assert derived.utc_ms(after) == after - 7200000
    assert derived.utc_ms(before - 1) == before - 1 - 10800000
    assert derived.confidence_at(before - 1) == "ASSUMED"
    # No version churn when the same evidence is re-derived.
    assert (
        derive_transitions(
            "fixture-eet",
            (
                BoundaryEvidence(t_broker_ms=before, t_utc_ms=before - 10800000),
                BoundaryEvidence(t_broker_ms=after, t_utc_ms=after - 7200000),
            ),
            derived,
        ).version
        == derived.version
    )


def test_clock_reconstruction_preserves_raw_and_changes_utc_identity(tmp_path: Path) -> None:
    raw = raw_bar(7200000)
    first = raw.normalize(clock(0))
    updated = clock(3600, 2)
    store = CandleStore(str(tmp_path / "history.duckdb"), "exness")
    store.put_broker(first)
    assert store.reproject(updated) == 1
    bars = store.read("M1", 0, 10000000)
    assert bars[0].t_open_ms == 3600000
    assert bars[0].id != first.bar.id
    assert store.raw_history("M1") == [raw]
    assert store.db.execute("SELECT t_broker_ms, clock_version FROM bars").fetchone() == (
        7200000,
        2,
    )
    store.close()


def test_reprojection_covers_history_before_live_measurement(tmp_path: Path) -> None:
    store = CandleStore(str(tmp_path / "history.duckdb"), "exness")
    original = raw_bar(60000).normalize(clock())
    store.put_broker(original)
    future_only = BrokerClock(
        broker="exness", transitions=((120000, 0),), version=2, derivation="measured"
    )
    assert store.reproject(future_only) == 1
    assert store.read("M1", 0, 120000)[0].clock_confidence == "ASSUMED"
    assert store.raw_history("M1") == [original.raw]
    store.close()


def test_raw_clock_fields_never_enter_wire_schema(tmp_path: Path) -> None:
    output = tmp_path / "wire.json"
    export_schema(output)
    schema = output.read_text()
    assert "t_broker_ms" not in schema
    assert "clock_version" not in schema


def test_goldens_fail_explicitly_when_clock_changes(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    first = clock()
    write_golden(path, "exness", [raw_bar(7200000).normalize(first)], first)
    assert read_golden(path, "exness", first.version, first.server)[0].t_open_ms == 7200000
    with pytest.raises(ValueError, match="server changed or missing, regenerate"):
        read_golden(path, "exness", first.version, "ExnessKE-MT5Real10")
    with pytest.raises(ValueError, match="clock changed, regenerate"):
        read_golden(path, "exness", 2, first.server)
    with pytest.raises(ValueError, match="clock changed, regenerate"):
        write_golden(path, "exness", [raw_bar(7200000).normalize(first)], clock(3600, 2))
    assert "t_broker_ms" not in path.read_text()


@pytest.mark.parametrize("offset", [0, 3600, -18000, 10800])
def test_independent_utc_argmax_matches_offset(offset: int) -> None:
    raw, vendor = price_window(epoch("2025-07-15T00:00"), offset)
    report = correlate_offsets(raw, vendor)
    assert report.offset_s == offset
    assert report.samples == 500
    assert report.correlation == pytest.approx(1)
    assert_alignment(report, clock(offset), raw)
    with pytest.raises(ValueError, match="vendor UTC alignment wins"):
        assert_alignment(report, clock(7200), raw)


def test_alignment_refuses_insufficient_coverage() -> None:
    raw, vendor = price_window(epoch("2025-01-15T00:00"), 0)
    with pytest.raises(ValueError, match="all candidate"):
        correlate_offsets(raw, vendor[700:1200])


def test_alignment_refuses_constant_prices() -> None:
    raw = [raw_bar(i * 60000 + 60000000) for i in range(500)]
    vendor = [
        Bar(
            tf="M1",
            t_open_ms=i * 60000,
            o=2000,
            h=2001,
            l=1999,
            c=2000,
            tick_volume=0,
            source="twelve_data",
            complete=True,
        )
        for i in range(2500)
    ]
    with pytest.raises(ValueError, match="constant-price"):
        correlate_offsets(raw, vendor)


def test_weekend_history_derivation_uses_price_evidence_not_dst_calendar() -> None:
    # The fixture changes on October 26. No EU/US calendar is consulted.
    raw_a, ref_a = price_window(epoch("2025-10-22T16:20"), 3600)
    raw_b, ref_b = price_window(epoch("2025-10-29T19:20"), 0)
    # Shift sample starts to raw 07:00 on successive days; preserve price evidence.
    delta_a = epoch("2025-10-23T07:00") - raw_a[0].t_broker_ms
    delta_b = epoch("2025-10-30T07:00") - raw_b[0].t_broker_ms
    raw_a = [
        RawBrokerBar.model_validate(b.model_dump() | {"t_broker_ms": b.t_broker_ms + delta_a})
        for b in raw_a
    ]
    raw_b = [
        RawBrokerBar.model_validate(b.model_dump() | {"t_broker_ms": b.t_broker_ms + delta_b})
        for b in raw_b
    ]
    refs = [
        Bar.model_validate(
            b.model_dump(exclude={"id", "object_hash"}) | {"t_open_ms": b.t_open_ms + delta_a}
        )
        for b in ref_a
    ]
    refs += [
        Bar.model_validate(
            b.model_dump(exclude={"id", "object_hash"}) | {"t_open_ms": b.t_open_ms + delta_b}
        )
        for b in ref_b
    ]

    class Vendor:
        def history(self, tf, start_ms, end_ms):
            return [b for b in refs if start_ms <= b.t_open_ms < end_ms]

    derived = derive_history_clock(raw_a + raw_b, Vendor(), "exness", (0, 3600), 0)
    assert derived.transitions == ((raw_a[0].t_broker_ms, 3600), (raw_b[0].t_broker_ms, 0))
    assert derived.derivation == "vendor_aligned"


def test_new_york_days_follow_us_dst_not_eu_dst() -> None:
    before = trading_day_bounds(epoch("2025-03-07T23:00"), "17:00 America/New_York")
    after = trading_day_bounds(epoch("2025-03-10T23:00"), "17:00 America/New_York")
    assert before[0] == epoch("2025-03-07T22:00")
    assert after[0] == epoch("2025-03-10T21:00")
    transition_day = trading_day_bounds(epoch("2025-03-09T10:00"), "17:00 America/New_York")
    assert transition_day[1] - transition_day[0] == 23 * 3600000
    week = trading_week_bounds(epoch("2025-03-10T10:00"), "17:00 America/New_York")
    assert week[0] == epoch("2025-03-09T21:00")


def test_daily_weekly_midnight_levels_use_m1_not_broker_days() -> None:
    start = epoch("2025-03-02T22:00")
    end = epoch("2025-03-11T06:00")
    bars = []
    for t in range(start, end, 60000):
        local_day_start = trading_day_bounds(t, "17:00 America/New_York")[0]
        price = 2000 + (local_day_start - start) / 86400000
        bars.append(raw_bar(t, price).normalize(clock()).bar)
    levels = analytical_levels(bars, end - 60000, SessionsConfig())
    previous = [
        b for b in bars if epoch("2025-03-09T21:00") <= b.t_open_ms < epoch("2025-03-10T21:00")
    ]
    assert levels.pdh == max(b.h for b in previous)
    assert levels.pdl == min(b.l for b in previous)
    assert levels.day_start_ms == epoch("2025-03-10T21:00")
    midnight = next(b for b in bars if b.t_open_ms == epoch("2025-03-11T04:00"))
    assert levels.midnight_open == midnight.o
    with pytest.raises(ValueError, match="broker D1/W1"):
        analytical_levels(
            [Bar.model_validate(bars[0].model_dump(exclude={"id", "object_hash"}) | {"tf": "D1"})],
            end,
        )


def test_phase_gate_requires_real_seasonal_proof(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="real January and July"):
        require_seasonal_proof(tmp_path / "absent.json", "exness", 1)


def test_canonical_server_group_cannot_silently_change(tmp_path: Path) -> None:
    store = CandleStore(str(tmp_path / "history.duckdb"), "exness")
    store.bind_server("Exness-MT5Real1")
    with pytest.raises(ValueError, match="server changed"):
        store.bind_server("Exness-MT5Real2")
    store.close()


def test_startup_exness_server_suffix_and_info_logging(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setattr("oracle.data.mt5_feed.time.time", lambda: 100000)

    class API:
        def initialize(self):
            return True

        def account_info(self):
            return SimpleNamespace(server="Exness-MT5Real1")

        def symbols_get(self):
            return [SimpleNamespace(name="XAUUSDm")]

        def symbol_select(self, symbol, selected):
            return True

        def symbol_info(self, symbol):
            return SimpleNamespace(
                digits=2, point=0.01, trade_tick_size=0.01, trade_contract_size=100
            )

        def symbol_info_tick(self, symbol):
            return SimpleNamespace(time=100000)

        def terminal_info(self):
            return SimpleNamespace(maxbars=2147483647)

    config = DataConfig(
        store_path=str(tmp_path / "bars.duckdb"), broker_clock_path=str(tmp_path / "clock.json")
    )
    feed = MT5Feed(API(), config)
    with caplog.at_level("INFO"):
        feed.startup()
    assert feed.broker_symbol == "XAUUSDm"
    assert feed.clock is not None and feed.clock.transitions[0][1] == 0
    assert "offset_s=0" in caplog.text
    assert feed._require_projection()[0].offset_ms_at(0) == 0
    assert feed.store is not None
    feed.store.close()


@pytest.mark.parametrize("measurement", [0, 3600])
def test_startup_utc_correlation_controls_ingestion(tmp_path, monkeypatch, measurement):
    raw, reference = price_window(epoch("2025-07-15T00:00"), 0)
    now = raw[-1].t_broker_ms // 1000 + 120
    monkeypatch.setattr("oracle.data.mt5_feed.time.time", lambda: now)
    rows = [
        {
            "time": b.t_broker_ms // 1000,
            "open": b.o,
            "high": b.h,
            "low": b.l,
            "close": b.c,
            "tick_volume": b.tick_volume,
        }
        for b in raw
    ]

    class Vendor:
        def history(self, tf, start_ms, end_ms):
            return [b for b in reference if start_ms <= b.t_open_ms < end_ms]

    class API:
        def initialize(self):
            return True

        def account_info(self):
            return SimpleNamespace(server="Exness-MT5Real1")

        def symbols_get(self):
            return [SimpleNamespace(name="XAUUSD")]

        def symbol_select(self, symbol, selected):
            return True

        def symbol_info(self, symbol):
            return SimpleNamespace(
                digits=2, point=0.01, trade_tick_size=0.01, trade_contract_size=100
            )

        def symbol_info_tick(self, symbol):
            return SimpleNamespace(time=now + measurement)

        def terminal_info(self):
            return SimpleNamespace(maxbars=2147483647)

        def copy_rates_from_pos(self, symbol, tf, pos, count):
            return rows

        TIMEFRAME_M1 = 1

    path = tmp_path / "clock.json"
    feed = MT5Feed(
        API(),
        DataConfig(store_path=str(tmp_path / "bars.duckdb"), broker_clock_path=str(path)),
        Vendor(),
    )
    if measurement:
        with pytest.raises(ValueError, match="vendor UTC alignment wins at 0s"):
            feed.startup()
        assert not path.exists()
        assert not feed.vendor_verified
    else:
        feed.startup()
        assert feed.vendor_verified
        assert feed.clock is not None
        assert feed.clock.confidence_at(raw[0].t_broker_ms) == "ASSUMED"
        assert feed.clock.utc_ms(raw[0].t_broker_ms) == raw[0].t_broker_ms
    assert feed.store is not None
    assert feed.store.raw_history("M1") == raw
    feed.store.close()


def test_stale_projection_rejected_and_tick_cannot_erase_provenance(tmp_path):
    store = CandleStore(str(tmp_path / "history.duckdb"), "exness")
    record = raw_bar(7200000).normalize(clock())
    store.put_broker(record)
    assert not store.put(record.bar)
    store.expect_clock(clock(3600, 2))
    with pytest.raises(ValueError, match="reconstruct UTC projection"):
        store.read("M1", 0, 10000000)
    assert store.reproject(clock(3600, 2)) == 1
    assert store.read("M1", 0, 10000000)[0].t_open_ms == 3600000
    store.close()


def test_calendar_provenance_is_current_clock_not_broker_time() -> None:
    from oracle.data.calendar import derive_calendar

    model = clock(3600, 4)
    # The raw 03:00 broker bar must enter the calendar as true UTC 02:00.
    converted = [raw_bar(t).normalize(model).bar for t in (10800000, 10860000, 10920000)]
    calendar = derive_calendar(converted, model)
    assert calendar.valid_from_ms == 7200000
    assert calendar.clock_version == 4
    assert calendar.canonical_broker == "exness"
