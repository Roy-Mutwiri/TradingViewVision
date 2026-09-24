import pytest
from pydantic import ValidationError

from oracle.analysis.contracts import Call
from oracle.analysis.explanations import reason_strip
from oracle.config import NarrationConfig


def call(**changes: object) -> Call:
    return Call.model_validate(dict(created_ms=1000, kind="SETUP", direction="LONG",
                                   entry_lo=100, entry_hi=101, invalidation=98, target=105,
                                   expires_ms=361000, state_hash="verified-state", reason="Stored evidence",
                                   reason_chain=["First stored fact", "Second stored fact",
                                                 "Third stored fact", "Fourth stored fact"],
                                   symbol="XAUUSD", clock_version=1) | changes)


def test_reason_strip_is_verbatim_three_lines_and_expires_at_twenty_seconds() -> None:
    original = call()
    drawing = reason_strip(original, 1000, 0)
    assert drawing and drawing.shape == "LABEL" and drawing.layer == "L3"
    assert drawing.text_args["label"] == "First stored fact\nSecond stored fact\nThird stored fact"
    assert drawing.reason == drawing.text_args["label"] and drawing.ttl_ms == 20000
    assert reason_strip(original, 20999, 0)
    assert reason_strip(original, 21000, 0) is None
    assert reason_strip(original, 999, 0) is None
    assert reason_strip(call(reason_chain=[]), 1000, 0) is None


def test_reason_chains_are_frozen_and_distinct_calls_have_distinct_drawings() -> None:
    original = call()
    assert isinstance(original.reason_chain, tuple)
    with pytest.raises(ValidationError):
        original.reason_chain = ("Retrospective edit",)
    other = call(reason="Separate call at the same level")
    first, second = reason_strip(original, 1000, 0), reason_strip(other, 1000, 0)
    assert first and second and first.id != second.id


def test_sound_cannot_be_enabled_by_configuration() -> None:
    assert NarrationConfig().audio is False
    with pytest.raises(ValidationError):
        NarrationConfig.model_validate({"audio": True})
