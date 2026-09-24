import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from oracle.analysis.contracts import Call, CallRow
from oracle.analysis.ledger import CallLedger
from oracle.analysis.resolver import CallResolver, QualityWindow
from oracle.analysis.scoring import board, statistics
from oracle.data.analytical_days import trading_day, trading_day_bounds
from oracle.models import Bar
from oracle.transport.errors import EngineError


def make_call(**changes: object) -> Call:
    return Call.model_validate(
        dict(
            created_ms=0,
            kind="SETUP",
            direction="LONG",
            entry_lo=100,
            entry_hi=100,
            invalidation=98,
            target=104,
            expires_ms=360000,
            state_hash="market-state-1",
            reason="Test call",
            symbol="XAUUSD",
            clock_version=1,
        )
        | changes
    )


def m1(t: int, low: float = 99.5, high: float = 100.5, close: float = 100, tf: str = "M1") -> Bar:
    return Bar.model_validate(
        dict(
            tf=tf,
            t_open_ms=t,
            o=close,
            h=high,
            l=low,
            c=close,
            tick_volume=1,
            source="synthetic",
            complete=True,
            digits=3,
        )
    )


def resolve(bars: list[Bar], **changes: object) -> tuple[Call, CallLedger]:
    ledger = CallLedger()
    call = ledger.create(make_call(**changes))
    result = CallResolver(ledger, 0.01).evaluate(call.id, bars, 360000, clock_version=1)
    return result, ledger


@pytest.mark.parametrize(
    "high,low,state,ambiguous",
    [
        (104, 98, "LOSS", True),
        (104, 99, "WIN", False),
        (101, 98, "LOSS", False),
    ],
)
def test_wick_exits_and_ambiguity(high: float, low: float, state: str, ambiguous: bool) -> None:
    result, ledger = resolve([m1(0), m1(60000, low, high)])
    assert result.state == state and result.resolved_ms == 120000
    assert ledger.row(result.id).ambiguous == ambiguous
    assert len([e for e in ledger.events if e.action == "AMBIGUOUS"]) == int(ambiguous)
    assert ledger.events[0].call.state == "PENDING"


def test_pending_expiry_and_active_expiry_are_visible_and_unscored() -> None:
    scratch, _ = resolve([m1(t) for t in range(0, 360000, 60000)])
    never, _ = resolve([m1(t, 101, 102, 101.5) for t in range(0, 360000, 60000)])
    assert scratch.state == "SCRATCH" and never.state == "NEVER_TRIGGERED"
    stats = statistics([CallRow(call=scratch), CallRow(call=never)])
    assert stats.scratch == 1 and stats.never_triggered == 1
    assert stats.hit_rate is None and stats.expectancy is None


def test_quality_outage_and_missing_coverage_require_visible_reason() -> None:
    ledger = CallLedger()
    call = ledger.create(make_call())
    resolver = CallResolver(ledger, 0.01)
    result = resolver.evaluate(
        call.id,
        [m1(0), m1(60000, 98, 104)],
        180000,
        clock_version=1,
        quality=[
            QualityWindow(
                start_ms=60000,
                end_ms=120000,
                state="STALE",
                reason="Terminal quote feed unavailable",
            )
        ],
    )
    assert result.state == "VOID_DATA"
    assert "STALE" in (ledger.row(call.id).resolution_reason or "")
    assert "Terminal quote feed unavailable" in ledger.events[-1].reason
    gap, gap_ledger = resolve([m1(0), m1(120000, 99, 104)])
    assert gap.state == "VOID_DATA" and "missing BID M1 coverage" in gap_ledger.events[-1].reason
    with pytest.raises(ValidationError):
        QualityWindow(start_ms=0, end_ms=60000, state="GAPPED", reason=" ")


def test_cancellation_is_append_only_and_can_never_resolve(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    ledger = CallLedger(path)
    call = ledger.create(make_call())
    before = path.read_bytes()
    ledger.cancel(call.id, "STRUCTURE_INVALIDATED_BEFORE_ENTRY", at_ms=10000)
    assert path.read_bytes().startswith(before)
    result = CallResolver(ledger, 0.01).evaluate(call.id, [m1(0, 98, 104)], 180000, clock_version=1)
    assert result.state == "CANCELLED" and ledger.row(call.id).cancelled
    restored = CallLedger(path)
    assert restored.rows == ledger.rows
    assert restored.row(call.id).cancellation_reason == "STRUCTURE_INVALIDATED_BEFORE_ENTRY"
    with pytest.raises(ValueError, match="cancelled"):
        ledger.advance(call.id, "WIN", 60000, 60000, "Not allowed")


def test_excluded_outcomes_do_not_inflate_hit_rate_or_expectancy() -> None:
    win, _ = resolve([m1(0), m1(60000, 99, 104)])
    loss, _ = resolve([m1(0), m1(60000, 98, 101)], reason="Different call")
    scratch, _ = resolve([m1(t) for t in range(0, 360000, 60000)], reason="Flat")
    never, _ = resolve([m1(t, 101, 102, 101.5) for t in range(0, 360000, 60000)], reason="No entry")
    baseline = statistics([CallRow(call=win), CallRow(call=loss)])
    expanded = statistics([CallRow(call=c) for c in (win, loss, scratch, never)])
    assert baseline.hit_rate == expanded.hit_rate == 0.5
    assert baseline.expectancy == expanded.expectancy == 0.5  # (+2R - 1R) / 2
    assert expanded.scratch == expanded.never_triggered == 1
    assert expanded.produced == 4 and expanded.triggered == 3


def test_required_terms_frozen_hash_and_idempotent_creation() -> None:
    call = make_call()
    for key in ("target", "invalidation", "expires_ms"):
        terms = call.model_dump()
        del terms[key]
        with pytest.raises(ValidationError):
            Call.model_validate(terms)
    with pytest.raises(ValidationError):
        call.target = 110
    with pytest.raises(ValidationError):
        Call.model_validate(call.model_dump() | {"target": 110})
    assert make_call(target=104.001).id != call.id
    ledger = CallLedger()
    ledger.create(call)
    ledger.create(call)
    assert len(ledger.events) == 1
    with pytest.raises(EngineError):
        make_call(kind="STRUCTURE", entry_hi=101)


def test_m1_only_epsilon_short_direction_and_terminal_finality() -> None:
    win, ledger = resolve([m1(0), m1(60000, 99, 103.995)])
    assert win.state == "WIN"
    resolver = CallResolver(ledger, 0.01)
    assert (
        resolver.evaluate(
            win.id,
            [],
            240000,
            clock_version=1,
            quality=[
                QualityWindow(start_ms=120000, end_ms=240000, state="GAPPED", reason="Later outage")
            ],
        )
        == win
    )
    short, _ = resolve([m1(0), m1(60000, 96, 101)], direction="SHORT", target=96, invalidation=102)
    assert short.state == "WIN"
    with pytest.raises(ValueError, match="M1"):
        resolve([m1(0, tf="M5")])


def test_display_windows_preserve_all_rows_and_use_explicit_today_boundary() -> None:
    rows = []
    for index in range(25):
        call = make_call(
            created_ms=index * 240000,
            expires_ms=(index + 1) * 240000,
            state="LOSS",
            resolved_ms=index * 240000 + 120000,
        )
        rows.append(CallRow(call=call))
    view = board(rows, 6000000)
    assert len(view.rows) == 25 and view.all_time.losses == 25
    assert view.last_20.losses == 20 and view.today.losses == 25


def test_fifty_call_frozen_resolution_set() -> None:
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "analysis_calls.json").read_text()
    )
    ledger = CallLedger()
    resolver = CallResolver(ledger, fixture["tick_size"])
    bars = [Bar.model_validate(value) for value in fixture["bars"]]
    actual = []
    for terms in fixture["calls"]:
        call = ledger.create(Call.model_validate(terms))
        result = resolver.evaluate(call.id, bars, fixture["now_ms"], clock_version=1)
        actual.append(
            {
                "id": result.id,
                "state": result.state,
                "resolved_ms": result.resolved_ms,
                "ambiguous": ledger.row(call.id).ambiguous,
            }
        )
    assert len(actual) == 50
    assert actual == fixture["expected"]


def test_active_cannot_cancel_and_cancelled_is_unscored_terminal() -> None:
    ledger = CallLedger()
    call = ledger.create(make_call())
    resolver = CallResolver(ledger, 0.01)
    resolver.evaluate(call.id, [m1(0)], 60000, clock_version=1)
    before = len(ledger.events)
    with pytest.raises(EngineError) as error:
        ledger.cancel(call.id, "OPERATOR_CANCELLED", at_ms=61000)
    assert error.value.fault.code == "CALL_ACTIVE_CANNOT_CANCEL"
    assert len(ledger.events) == before
    second = ledger.create(make_call(reason="Independent new analysis"))
    ledger.cancel(second.id, "SUPERSEDED_BY_NEW_ANALYSIS", at_ms=10000)
    assert (
        resolver.evaluate(second.id, [m1(0, 98, 104)], 360000, clock_version=1).state == "CANCELLED"
    )
    baseline = statistics([CallRow(call=make_call(state="WIN", resolved_ms=60000))])
    expanded = statistics(
        [CallRow(call=make_call(state="WIN", resolved_ms=60000)), ledger.row(second.id)]
    )
    assert baseline.hit_rate == expanded.hit_rate == 1
    assert expanded.cancelled == 1
    with pytest.raises(EngineError) as error:
        ledger.cancel(call.id, "OPERATOR_CANCELLED")
    assert error.value.fault.code == "CALL_ACTIVE_CANNOT_CANCEL"


@pytest.mark.parametrize(
    "direction,high,low,state,ambiguous",
    [
        ("LONG", 104, 99, "WIN", False),
        ("LONG", 101, 98, "LOSS", False),
        ("LONG", 104, 98, "LOSS", True),
        ("SHORT", 101, 96, "WIN", False),
        ("SHORT", 102, 99, "LOSS", False),
        ("SHORT", 102, 96, "LOSS", True),
    ],
)
def test_activation_bar_geometry(
    direction: str, high: float, low: float, state: str, ambiguous: bool
) -> None:
    result, ledger = resolve(
        [m1(0, low, high)],
        direction=direction,
        target=104 if direction == "LONG" else 96,
        invalidation=98 if direction == "LONG" else 102,
    )
    assert result.state == state and result.resolved_ms == 60000
    assert ledger.row(result.id).ambiguous == ambiguous


def test_creation_and_expiry_partial_minutes_are_excluded_symmetrically() -> None:
    zone = ZoneInfo("America/New_York")
    created = int(datetime(2026, 9, 18, 14, 22, 37, tzinfo=zone).timestamp() * 1000)
    expiry = int(datetime(2026, 9, 18, 18, 5, 12, tzinfo=zone).timestamp() * 1000)
    ledger = CallLedger()
    call = ledger.create(make_call(created_ms=created, expires_ms=expiry))
    assert datetime.fromtimestamp(call.eval_from_ms / 1000, zone).strftime("%H:%M") == "14:23"
    assert (
        datetime.fromtimestamp((call.eval_to_ms - 60000) / 1000, zone).strftime("%H:%M") == "18:04"
    )
    bars = [m1(t) for t in range(call.eval_from_ms, call.eval_to_ms, 60000)]
    bars += [m1(created // 60000 * 60000, 98, 104), m1(expiry // 60000 * 60000, 98, 104)]
    result = CallResolver(ledger, 0.01).evaluate(call.id, bars, expiry, clock_version=1)
    assert result.state == "SCRATCH" and result.resolved_ms == expiry


def test_weekend_gap_past_zone_and_target_never_triggers() -> None:
    ledger = CallLedger()
    call = ledger.create(make_call(expires_ms=3 * 86400000))
    resolver = CallResolver(ledger, 0.01)
    reopening = 2 * 86400000
    bars = [m1(0, 96, 97, 96.5)] + [
        m1(t, 105, 106, 105.5) for t in range(reopening, call.expires_ms, 60000)
    ]
    result = resolver.evaluate(
        call.id,
        bars,
        call.expires_ms,
        clock_version=1,
        is_tradeable=lambda t: t < 60000 or t >= reopening,
    )
    assert result.state == "NEVER_TRIGGERED" and result.gap_skipped
    assert statistics(ledger.rows).gap_skipped == 1


def test_invalid_geometry_missing_terms_and_short_life_write_nothing(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    ledger = CallLedger(path)
    terms = make_call().model_dump(exclude={"id"})
    for changes, code in [
        ({"target": 99}, "CALL_GEOMETRY_INVALID"),
        ({"invalidation": 101}, "CALL_GEOMETRY_INVALID"),
        ({"expires_ms": 300000, "eval_to_ms": 0}, "CALL_LIFE_TOO_SHORT"),
    ]:
        with pytest.raises(EngineError) as error:
            ledger.submit(terms | changes)
        assert error.value.fault.code == code
        assert not ledger.events and not path.exists()
    for field in ("target", "invalidation", "expires_ms"):
        missing = dict(terms)
        del missing[field]
        with pytest.raises(EngineError) as error:
            ledger.submit(missing)
        assert error.value.fault.code == "CALL_NOT_FALSIFIABLE"
        assert not ledger.events and not path.exists()


def test_produced_call_entry_ref_must_equal_recorded_trigger_price() -> None:
    terms = make_call(timeframe="M15", entry_ref=100).model_dump(exclude={"id"})
    with pytest.raises(EngineError) as error:
        Call.model_validate(terms | {"trigger_price": 99.5})
    assert error.value.fault.code == "CALL_ENTRY_TRIGGER_MISMATCH"
    ledger = CallLedger()
    call = ledger.create(Call.model_validate(terms))
    active = CallResolver(ledger, 0.01).evaluate(call.id, [m1(0)], 60000, clock_version=1)
    assert active.state == "ACTIVE"
    assert active.entry_ref == active.trigger_price == 100


def test_resolution_day_is_shared_with_levels_and_dst_aware() -> None:
    zone = ZoneInfo("America/New_York")

    def stamp(hour: int, minute: int) -> int:
        return int(datetime(2026, 9, 18, hour, minute, tzinfo=zone).timestamp() * 1000)

    before, after = stamp(16, 58), stamp(17, 2)
    calls = [
        make_call(
            created_ms=stamp(10, 0),
            expires_ms=stamp(18, 0),
            state="WIN",
            resolved_ms=value,
            reason=str(value),
        )
        for value in (before, after)
    ]
    assert calls[0].created_trading_day == calls[1].created_trading_day
    assert calls[0].resolved_trading_day != calls[1].resolved_trading_day
    view = board([CallRow(call=c) for c in calls], stamp(17, 5))
    assert view.today.wins == 1 and view.all_time.wins == 2
    assert view.today_label == "TODAY · from 17:00 NY"
    for month, day, hours in [(3, 8, 23), (11, 1, 25)]:
        t = int(datetime(2026, month, day, 12, tzinfo=zone).timestamp() * 1000)
        lo, hi = trading_day_bounds(t, "17:00 America/New_York")
        assert hi - lo == hours * 3600000
        assert (
            trading_day(lo).isoformat()
            == datetime.fromtimestamp(lo / 1000, zone).date().isoformat()
        )


def test_ingestion_grace_does_not_turn_a_not_yet_finalized_minute_into_void() -> None:
    ledger = CallLedger()
    call = ledger.create(make_call())
    resolver = CallResolver(ledger, 0.01)
    result = resolver.evaluate(call.id, [], 60000, clock_version=1, coverage_through_ms=58500)
    assert result.state == "PENDING"
    result = resolver.evaluate(
        call.id, [m1(0, 99, 104)], 62000, clock_version=1, coverage_through_ms=60500
    )
    assert result.state == "WIN"


def test_range_spanning_a_zone_enters_and_does_not_cherry_pick_duplicate_bars() -> None:
    ledger = CallLedger()
    call = ledger.create(make_call(entry_hi=101))
    resolver = CallResolver(ledger, 0.01)
    assert resolver.evaluate(call.id, [m1(0, 99, 102)], 60000, clock_version=1).state == "ACTIVE"
    with pytest.raises(ValueError, match="Conflicting"):
        resolver.evaluate(
            call.id, [m1(60000, 99, 104), m1(60000, 98, 102)], 120000, clock_version=1
        )


def test_pending_call_waits_for_an_active_slot_before_triggering() -> None:
    ledger = CallLedger()
    call = ledger.create(make_call(entry_hi=101))
    resolver = CallResolver(ledger, 0.01)
    blocked = resolver.evaluate(
        call.id,
        [m1(0, 99, 102)],
        60000,
        clock_version=1,
        can_activate=lambda _: False,
    )
    assert blocked.state == "PENDING"
    admitted = resolver.evaluate(
        call.id,
        [m1(60000, 99, 102)],
        120000,
        clock_version=1,
        can_activate=lambda _: True,
    )
    assert admitted.state == "ACTIVE"
    assert admitted.trigger_price == admitted.entry_ref
