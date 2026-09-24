from types import SimpleNamespace

import pytest

from oracle.data.calendar import derive_calendar, local_session_ms
from oracle.data.candle_store import CandleStore
from oracle.data.instrument import Instrument
from oracle.data.mt5_feed import derive_offset
from oracle.models import Bar, timeframe_ms


def bar(t: int = 0, source: str = "mt5", price: float = 2000.001) -> Bar:
    return Bar(
        tf="M1",
        t_open_ms=t,
        o=price,
        h=price,
        l=price,
        c=price,
        tick_volume=1,
        source=source,
        complete=True,
    )


def test_dst_offset_fixture() -> None:
    # October 25/26, 2025: stipulated server-clock input changes EEST -> EET.
    for now, offset in [(1761393600, 10800), (1761480000, 7200)]:
        assert derive_offset(now + offset, now) == offset
    with pytest.raises(ValueError):
        derive_offset(14400, 0)


def test_vendor_cannot_overwrite(tmp_path) -> None:
    store = CandleStore(str(tmp_path / "bars.duckdb"), "fixture-broker")
    assert store.put(bar(source="twelve_data"))
    assert store.read("M1", 0, 60000)[0].source == "twelve_data"
    assert store.put(bar())
    assert not store.put(bar(source="twelve_data"))
    assert store.read("M1", 0, 60000)[0].source == "mt5"
    store.close()


def test_instrument_assertions() -> None:
    info = SimpleNamespace(digits=3, point=0.001, trade_tick_size=0.001, trade_contract_size=100)
    instrument = Instrument.from_mt5(info)
    assert instrument.usd_per_point_per_lot == 0.1
    assert instrument.contains(2000, 2001, 2000)
    for digits, contract in [(4, 100), (2, 10)]:
        with pytest.raises(ValueError):
            Instrument.from_mt5(SimpleNamespace(digits=digits, trade_contract_size=contract))


def test_noise_identity_and_month_arithmetic() -> None:
    assert bar(price=2000.001).id == bar(price=2000.002).id
    with pytest.raises(ValueError):
        timeframe_ms("MN1")


def test_observed_calendar() -> None:
    minute = 60000
    series = [bar(t=i * minute) for i in range(14 * 1440) if i % 1440 < 1380]
    calendar = derive_calendar(series)
    for i in range(14 * 1440 - 60):
        assert calendar.is_tradeable(i * minute) == (i % 1440 < 1380)
    assert local_session_ms("2025-10-27", "08:00", "Europe/London") != local_session_ms(
        "2025-10-24", "08:00", "Europe/London"
    )


def test_short_early_close_matches_measured_reopen_but_mid_session_hole_does_not() -> None:
    minute = 60000
    series = [
        bar(t=i * minute)
        for i in range(35 * 1440)
        if not (1260 <= i % 1440 < 1320)
        and not (i // 1440 == 7 and 1110 <= i % 1440 < 1320)
        and not (i // 1440 == 9 and 720 <= i % 1440 < 740)
    ]
    calendar = derive_calendar(series)
    start, end = (7 * 1440 + 1110) * minute, (7 * 1440 + 1320) * minute
    assert calendar.explains(start, end)
    assert any(c.start_ms == start and not c.recurring for c in calendar.closures)
    assert not calendar.explains((9 * 1440 + 720) * minute, (9 * 1440 + 740) * minute)


def test_lifecycle_keeps_identity_changes_render() -> None:
    from oracle.models import Zone

    zone = Zone(
        kind="OB",
        direction="BULLISH",
        tf="M5",
        t_start_ms=0,
        t_end_ms=300000,
        price_hi=2001,
        price_lo=2000,
        state="FRESH",
        fill_pct=0,
        score=0.8,
        reason="fixture",
        source_bars=[0],
    )
    touched = zone.transition(state="TOUCHED", fill_pct=30)
    assert touched.id == zone.id
    assert touched.object_hash != zone.object_hash
    assert zone.state == "FRESH"


def test_tick_correction(tmp_path) -> None:
    from oracle.data.ticks import TickBuilder

    builder = TickBuilder(0.01, 2)
    builder.ingest(0, 2000)
    builder.ingest(1000, 2001)
    closed = builder.ingest(60000, 2002)
    assert closed is not None and closed.tick_volume == 2
    broker = Bar(
        tf="M1",
        t_open_ms=0,
        o=2000,
        h=2002,
        l=2000,
        c=2001,
        tick_volume=3,
        source="mt5",
        complete=True,
    )
    store = CandleStore(str(tmp_path / "ticks.duckdb"), "fixture-broker")
    correction = builder.reconcile(closed, broker, store)
    assert correction is not None
    assert store.read("M1", 0, 60000)[0] == broker
    store.close()


def test_proof_rejects_missing_edge_bar() -> None:
    from oracle.data.calendar import TradingCalendar
    from oracle.replay.harness import replay_proof

    duration = 30 * 86400000
    calendar = TradingCalendar(valid_from_ms=0, valid_to_ms=duration, closures=())
    sample = Bar(
        tf="M5",
        t_open_ms=300000,
        o=2000,
        h=2000,
        l=2000,
        c=2000,
        tick_volume=1,
        source="mt5",
        complete=True,
    )
    with pytest.raises(ValueError, match="Unexplained"):
        replay_proof([sample], calendar, 0, duration)
