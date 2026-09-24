import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from oracle.bus import BusOverflow, EventBus
from oracle.clock import ReplayClock
from oracle.config import OracleConfig, load_config
from oracle.models import Bar, DrawObject, Quote, Scenario, Swing, WireEvent
from oracle.ops.dashboard import create_dashboard
from oracle.transport.protocol import export_schema


def bar() -> Bar:
    return Bar(
        symbol="XAUUSD",
        tf="M1",
        t_open_ms=60000,
        o=10,
        h=12,
        l=9,
        c=11,
        tick_volume=2,
        source="mt5",
        complete=True,
    )


def test_bar_validation() -> None:
    for changes in (
        {"h": 8},
        {"t_open_ms": -1},
        {"o": float("nan")},
        {"extra": 2},
        {"t_open_ms": 1.5},
    ):
        with pytest.raises(ValidationError):
            Bar.model_validate(bar().model_dump() | changes)
    with pytest.raises(ValidationError):
        Quote(symbol="XAUUSD", bid=2, ask=1, t_ms=0, source="test")


def test_hash_roundtrip() -> None:
    swing = Swing(kind="HH", idx=1, t_ms=60000, price=12, tf="M1")
    assert Swing.model_validate_json(swing.canonical_json()) == swing
    assert len(swing.id) == 16
    with pytest.raises(ValidationError):
        Swing.model_validate(swing.model_dump() | {"price": 13})


def test_drawing_reason_chain() -> None:
    data = dict(
        layer="L2",
        shape="ZONE",
        points=[{"t_ms": 0, "price": 10}],
        style={"token": "ob.bullish"},
        text_key="zone.ob",
        text_args={},
        state="FRESH",
        ttl_ms=1000,
        priority=1,
        z=2,
        anim={"in_": "wipe", "loop": None},
        reason="Bar 0 displacement",
        source_bars=[0],
        confidence=0.8,
    )
    drawing = DrawObject.model_validate(data)
    assert drawing.id != drawing.object_hash
    assert DrawObject.model_validate_json(drawing.canonical_json()) == drawing
    for changes in ({"reason": " "}, {"source_bars": []}, {"confidence": 1.1}):
        with pytest.raises(ValidationError):
            DrawObject.model_validate(data | changes)


def test_probability_needs_sample() -> None:
    with pytest.raises(ValidationError):
        Scenario(
            rank="PRIMARY",
            direction="BULLISH",
            waypoints=[{"price": 10, "kind": "TARGET", "note": "target"}],
            invalidation_price=9,
            probability=0.6,
            prob_sample_n=0,
            expected_move_atr=2,
            valid_until_ms=60000,
            reason_chain=["test"],
        )


def test_clock() -> None:
    clock = ReplayClock(10)
    clock.advance_to(20)
    assert clock.now_ms() == 20
    with pytest.raises(ValueError):
        clock.advance_to(19)


@pytest.mark.asyncio
async def test_bus_atomic_overflow_and_cleanup() -> None:
    bus = EventBus(1)
    event = WireEvent(sequence=0, t_ms=60000, payload=bar())
    async with bus.subscribe() as first, bus.subscribe() as second:
        await bus.publish(event)
        assert await first.get() == event
        with pytest.raises(BusOverflow):
            await bus.publish(event)
        assert first.empty()
        assert await second.get() == event
    await bus.publish(event)
    assert not bus._queues
    await asyncio.sleep(0)


def test_config_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "oracle.yaml"
    path.write_text("data:\n  canonical_symbol: XAUUSD\n")
    monkeypatch.setenv("ORACLE__DATA__STALE_MS", "5000")
    assert load_config(path).data.stale_ms == 5000
    monkeypatch.setenv("ORACLE__DATA__TYPO", "true")
    with pytest.raises(ValidationError):
        load_config(path)


def test_dashboard_and_schema(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    app = create_dashboard(OracleConfig(language="ar"), root / "config/strings")
    with TestClient(app) as client:
        assert client.get("/health").json()["phase_gate"] == "pending"
        assert 'dir="rtl"' in client.get("/").text
        assert client.get("/events").json() == []
    output = tmp_path / "protocol.json"
    export_schema(output)
    assert '"PresentationBeat"' in output.read_text()
