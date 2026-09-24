import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from oracle.data.broker_bar import RawBrokerBar
from oracle.data.broker_clock import BoundaryEvidence, BrokerClock, OffsetSpan, derive_transitions
from oracle.data.candle_store import CandleStore
from oracle.data.golden_source import write_golden
from oracle.data.history_warmup import warm_history
from oracle.replay.golden import read_golden
from oracle.transport.errors import EngineError, boundary_error


def fresh():
    return BrokerClock(
        broker="exness",
        server="ExnessKE-MT5Trial10",
        spans=(
            OffsetSpan(from_broker_ms=None, to_broker_ms=None, offset_s=0, confidence="MEASURED"),
        ),
        measured_from_broker_ms=1789684980000,
        version=1,
    )


@given(st.integers(min_value=-(2**63), max_value=2**63 - 1))
@example(-(2**63))
@example(2**63 - 1)
def test_clock_always_answers_all_int64(t):
    assert fresh().offset_ms_at(t) == 0
    assert fresh().confidence_at(t) in ("MEASURED", "ASSUMED")


def test_clock_rejects_holes():
    with pytest.raises(ValueError, match="gapless"):
        BrokerClock(
            broker="exness",
            version=1,
            spans=(
                OffsetSpan(from_broker_ms=None, to_broker_ms=10, offset_s=0, confidence="ASSUMED"),
                OffsetSpan(
                    from_broker_ms=11, to_broker_ms=None, offset_s=3600, confidence="DERIVED"
                ),
            ),
        )


def test_refinement_reprojects_raw_and_invalidates_provisional_goldens(tmp_path):
    clock = fresh()
    raw = RawBrokerBar(
        tf="M1",
        t_broker_ms=1789000020000,
        o=4351,
        h=4353,
        l=4350,
        c=4352,
        tick_volume=400,
        digits=2,
        complete=True,
    )
    store = CandleStore(":memory:", "exness")
    record = raw.normalize(clock)
    store.put_broker(record)
    path = tmp_path / "provisional.json"
    write_golden(path, "exness", [record], clock)
    header = json.loads(path.read_text())
    assert header["clock_confidence"] == "ASSUMED" and header["provisional"]
    refined = derive_transitions(
        "exness",
        (BoundaryEvidence(t_broker_ms=raw.t_broker_ms, t_utc_ms=raw.t_broker_ms - 3600000),),
        clock,
    )
    assert refined.version == 2 and refined.server == clock.server
    assert store.reproject(refined) == 1
    new = store.read("M1", 0, raw.t_broker_ms + 1)[0]
    assert new.t_open_ms == raw.t_broker_ms - 3600000
    assert new.clock_confidence == "DERIVED"
    assert store.raw_history("M1")[0].t_broker_ms == raw.t_broker_ms
    with pytest.raises(ValueError, match="clock refined, regenerate"):
        read_golden(path, "exness", refined.version, refined.server)
    store.close()


def test_typed_errors_preserve_cause_and_redact_unknown_exception_text():
    error = EngineError(
        "SYMBOL_UNRESOLVED", "Select an available spot gold symbol.", {"candidates": ["XAUUSDz"]}
    )
    assert boundary_error(error, "chart_subscribe").wire()["code"] == "SYMBOL_UNRESOLVED"
    unknown = boundary_error(ValueError("password=fixture-secret"), "chart_subscribe").wire()
    assert "fixture-secret" not in json.dumps(unknown)
    assert unknown["detail"]["exception_type"] == "ValueError"
    try:
        raise ValueError("password=fixture-secret")
    except ValueError as exc:
        traced = boundary_error(exc, "chart_poll").wire()
    assert "fixture-secret" not in json.dumps(traced)
    assert (
        traced["detail"]["frames"][-1]["function"]
        == "test_typed_errors_preserve_cause_and_redact_unknown_exception_text"
    )


def test_generic_boundary_messages_are_forbidden_in_sources():
    root = Path(__file__).resolve().parents[3]
    for folder in (root / "engine/oracle", root / "app/electron", root / "app/src"):
        for path in folder.rglob("*"):
            if path.suffix in (".py", ".ts", ".tsx"):
                assert "operation failed" not in path.read_text(encoding="utf-8").lower(), str(path)


def test_warmup_requests_descending_chunks():
    calls = []

    def rates(symbol, tf, end, count):
        calls.append((symbol, tf, end, count))
        t = int(end.timestamp())
        return [{"time": t - 60 * (i + 1)} for i in reversed(range(min(2, count)))]

    api = SimpleNamespace(copy_rates_from=rates, TIMEFRAME_M1=1)
    warm_history(api, "XAUUSDz", "M1", 5, 1789684980000)
    assert len(calls) == 3
    assert calls[0][2] > calls[1][2] > calls[2][2]
    assert [c[3] for c in calls] == [5, 3, 1]
def test_closed_market_retains_saved_clock_without_claiming_proof(monkeypatch):
    from datetime import UTC, datetime
    from oracle.config import DataConfig
    from oracle.data.mt5_feed import MT5Feed
    last = datetime(2026, 9, 18, 21, 0, tzinfo=UTC).timestamp()
    now = last + 900
    api = SimpleNamespace(symbol_info_tick=lambda _: SimpleNamespace(time=last), account_info=lambda: SimpleNamespace(server='ExnessKE-MT5Trial10'))
    feed = MT5Feed(api, DataConfig(canonical_broker='exness', expected_offset_s=[0, 3600]))
    feed.clock = fresh()
    original = feed.clock
    monkeypatch.setattr('oracle.data.mt5_feed.time.time', lambda: now)
    feed.refresh_offset(startup=True)
    assert feed.clock is original
    assert feed.vendor_verified is False
    api.account_info = lambda: SimpleNamespace(server='ExnessKE-MT5Real10')
    with pytest.raises(ValueError, match='server differs'):
        feed.refresh_offset(startup=True)
