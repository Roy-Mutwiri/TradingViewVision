"""The speaker sink and frame projection (docs/ORACLE_BRIDGE.md).

Two things are load-bearing and get the most attention here: the sink can never affect the worker, and
hit_rate/expectancy can never cross the boundary.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from oracle.ops.speaker_frame import (
    FORBIDDEN_SCOREBOARD_FIELDS,
    build_frame,
    levels_of,
    mss_wired,
    scoreboard_of,
    session_of,
    structure_of,
)
from oracle.ops.speaker_sink import FRAME_VERSION, SpeakerSink


def _pool(name: str, level: float, *, state: str = "FRESH", side: str = "HIGH") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        geometry=types.SimpleNamespace(name=name, level=level, side=side),
        state=state,
        named=True,
        swept_ms=None,
    )


# --------------------------------------------------------------------------- the safety contract
def test_the_sink_drops_the_oldest_frame_instead_of_blocking(tmp_path: Path) -> None:
    sink = SpeakerSink(tmp_path, queue_size=4)
    for n in range(10):
        sink.offer({"seq": n})
    assert sink.stats["offered"] == 10
    assert sink.stats["dropped"] == 6  # bounded: the six oldest went, the four newest stayed
    assert sink.latest() == {"seq": 9}  # and the newest market state is what /state serves


def test_offer_never_raises_even_on_an_unserialisable_frame(tmp_path: Path) -> None:
    sink = SpeakerSink(tmp_path, queue_size=2)
    sink.start()
    sink.offer({"bad": object()})  # not JSON-serialisable
    sink.offer({"seq": 1})
    sink.stop()
    assert sink.stats["offered"] == 2  # nothing propagated to the caller


def test_a_sink_that_cannot_open_its_directory_does_not_raise(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    sink = SpeakerSink(blocker)  # mkdir will fail
    sink.start()
    sink.offer({"seq": 1})
    sink.stop()
    assert sink.stats["errors"] >= 1  # counted, not thrown


def test_frames_are_written_as_one_json_object_per_line(tmp_path: Path) -> None:
    sink = SpeakerSink(tmp_path)
    sink.start()
    for n in range(3):
        sink.offer({"v": FRAME_VERSION, "seq": n})
    assert sink.flush() is True
    sink.stop()
    written = list(tmp_path.glob("frames-*.jsonl"))
    assert len(written) == 1
    rows = [json.loads(line) for line in written[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [r["seq"] for r in rows] == [0, 1, 2]


def test_rotation_keeps_the_directory_bounded(tmp_path: Path) -> None:
    sink = SpeakerSink(tmp_path, max_bytes=100_000, keep_files=2)
    sink.start()
    sink._written = 100_000  # force the next write over the limit
    sink.offer({"seq": 1})
    assert sink.flush() is True
    sink.stop()
    assert sink.stats["rotations"] == 1


# --------------------------------------------------------------------------- section 7: the hard rule
def test_hit_rate_and_expectancy_never_reach_the_frame() -> None:
    board = types.SimpleNamespace(
        today=types.SimpleNamespace(
            produced=14, triggered=9, resolved=7, scratch=1, cancelled=2, never_triggered=3,
            hit_rate=0.71, expectancy=0.45,
        ),
        today_label="TODAY",
    )
    projection = scoreboard_of(board)
    assert projection["produced"] == 14 and projection["resolved"] == 7
    for banned in FORBIDDEN_SCOREBOARD_FIELDS:
        assert banned not in projection
    assert "0.71" not in json.dumps(projection) and "0.45" not in json.dumps(projection)


def test_the_whole_frame_is_free_of_performance_claims() -> None:
    frame = build_frame(
        seq=1, now_ms=1_790_000_000_000, tf="M15", bid=4351.1, ask=4351.4, tick_ms=1_790_000_000_000,
        quality=types.SimpleNamespace(state="OK", staleness_ms=10, spread_points=30),
        next_close_ms=None, bar_duration_ms=900_000, structure_state=None,
        pools=[_pool("PDH", 4381.34)], weekly_open=None,
        retention=types.SimpleNamespace(
            hook=None,
            scoreboard=types.SimpleNamespace(
                today=types.SimpleNamespace(
                    produced=1, triggered=1, resolved=1, scratch=0, cancelled=0, never_triggered=0,
                    hit_rate=1.0, expectancy=2.0,
                ),
                today_label="TODAY",
            ),
        ),
        intervals=[], market_closed=False, next_open_ms=None,
    )
    blob = json.dumps(frame)
    assert "hit_rate" not in blob and "expectancy" not in blob


# --------------------------------------------------------------------------- section 4: the translation traps
def test_choch_spelling_and_direction_are_normalised() -> None:
    state = types.SimpleNamespace(
        trend="BEARISH", trend_since_ms=1_790_036_100_000, protected_high=4372.4, protected_low=None,
        last_event=types.SimpleNamespace(
            kind="CHoCH", is_mss=False, direction="DOWN", level=4368.9, break_close=4366.2,
            t_ms=1_790_036_100_000, id="abc",
        ),
    )
    out = structure_of(state, "M15")
    assert out is not None
    assert out["last_event"]["kind"] == "CHOCH"  # ORACLE spells it "CHoCH"
    assert out["last_event"]["direction"] == "BEARISH"  # ORACLE says "DOWN"
    assert out["trend_since_ms"] == 1_790_036_100_000
    assert out["protected_high"] == 4372.4 and out["protected_low"] is None


def test_mss_is_a_choch_with_the_flag_not_a_kind() -> None:
    event = types.SimpleNamespace(
        kind="CHoCH", is_mss=True, direction="UP", level=1.0, break_close=1.0, t_ms=1, id="x"
    )
    out = structure_of(types.SimpleNamespace(trend="BULLISH", trend_since_ms=1, protected_high=None,
                                             protected_low=None, last_event=event), "M15")
    assert out is not None and out["last_event"]["kind"] == "MSS" and out["last_event"]["is_mss"] is True


def test_mss_detection_is_reported_so_the_speaker_can_refuse_to_claim_it() -> None:
    assert mss_wired([]) is False  # no liquidity engine ran: is_mss would be permanently False
    assert mss_wired([_pool("PDH", 1.0)]) is True


def test_distance_in_points_uses_the_instruments_own_point_size() -> None:
    """The live broker quotes gold to three decimals, so point = 0.001 and a hard-coded 10**2 is out by ten."""
    two = levels_of([_pool("PDH", 4381.34), _pool("PDL", 4266.11, side="LOW")], None, 4351.20, 0.01)
    by_name = {row["name"]: row for row in two}
    assert by_name["PDH"]["distance_points"] == 3014
    assert by_name["PDL"]["distance_points"] == -8509
    assert [row["name"] for row in two] == ["PDH", "PDL"]  # nearest first

    three = levels_of([_pool("PDH", 4381.34)], None, 4351.20, 0.001)
    assert three[0]["distance_points"] == 30140  # same gap, the instrument's own unit

    assert levels_of([_pool("PDH", 1.0)], None, None, 0.001)[0]["distance_points"] is None


def test_the_weekly_open_becomes_a_named_level() -> None:
    levels = levels_of([], 4302.11, 4351.20, 0.01)
    assert levels[0]["name"] == "WEEKLY OPEN" and levels[0]["price"] == 4302.11


def test_no_english_is_emitted_because_oracle_ships_seven_languages() -> None:
    levels = levels_of([_pool("ASIA H", 4372.1)], None, 4351.2, 0.01)
    assert levels[0]["name"] == "ASIA H"
    assert "provenance" not in levels[0]  # the spoken form is mapped on the speaker side


def test_session_state_is_computed_because_killzones_is_a_stub() -> None:
    intervals = [types.SimpleNamespace(key="LONDON", start_ms=1000, end_ms=2000)]
    assert session_of(1500, intervals, False, None)["name"] == "LONDON"
    assert session_of(2500, intervals, False, None)["name"] == "BETWEEN"
    closed = session_of(1500, intervals, True, 9999)
    assert closed["name"] == "CLOSED" and closed["next_open_ms"] == 9999


@pytest.mark.parametrize("bid,ask", [(None, None), (0.0, 0.0)])
def test_no_quote_means_no_price_rather_than_a_guess(bid: float | None, ask: float | None) -> None:
    frame = build_frame(
        seq=1, now_ms=1, tf="M15", bid=bid, ask=ask, tick_ms=None, quality=None, next_close_ms=None,
        bar_duration_ms=None, structure_state=None, pools=[], weekly_open=None,
        retention=types.SimpleNamespace(hook=None, scoreboard=None), intervals=[],
        market_closed=False, next_open_ms=None,
    )
    assert frame["price"] is None
    assert frame["v"] == FRAME_VERSION
