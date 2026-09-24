from oracle.analysis.call_drawing import call_objects
from oracle.analysis.contracts import Call, CallRow


def _call(state: str, created: int = 1_000_000, resolved: int | None = None) -> Call:
    return Call(
        created_ms=created,
        kind="SETUP",
        direction="LONG",
        entry_lo=100,
        entry_hi=101,
        entry_ref=101,
        invalidation=99,
        target=104,
        expires_ms=created + 900_000,
        state_hash="state",
        reason="test call",
        reason_chain=("test",),
        symbol="XAUUSD",
        clock_version=1,
        state=state,  # type: ignore[arg-type]
        resolved_ms=resolved,
        timeframe="M15",
        ob_id="ob",
        structure_event_id="structure",
        target_pool_id="pool",
    )


def test_resolved_call_ghost_renders_only_after_resolution_window() -> None:
    future = CallRow(call=_call("NEVER_TRIGGERED", resolved=2_000_000))
    assert call_objects([future], 1_500_000, 100) == []

    fresh = CallRow(call=_call("LOSS", resolved=1_495_000))
    assert any(obj.style.token == "call.trade" for obj in call_objects([fresh], 1_500_000, 100))

    stale = CallRow(call=_call("WIN", resolved=1_490_000))
    assert call_objects([stale], 1_500_000, 100) == []


def test_open_call_renders_until_it_resolves() -> None:
    pending = CallRow(call=_call("PENDING", resolved=None))
    objects = call_objects([pending], 1_500_000, 100)
    assert any(obj.style.token == "call.trade" for obj in objects)
    assert any(obj.style.token == "call.level" and obj.text_args["level_role"] == "TP1" for obj in objects)
