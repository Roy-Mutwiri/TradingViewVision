from pathlib import Path

import pytest

from oracle.analysis.contracts import Call
from oracle.analysis.resolver import CallResolver
from oracle.director.director import Director
from oracle.director.gamechanger import GamechangerTail, ingest_record
from oracle.director.moderation import display_handle, handle_key
from oracle.director.timeline import Timeline, retention_report
from oracle.models import Bar


def candle(t: int, c: float = 101, complete: bool = True) -> Bar:
    return Bar(
        symbol="XAUUSD",
        tf="M1",
        t_open_ms=t,
        o=100,
        h=max(102, c),
        l=min(99, c),
        c=c,
        tick_volume=10,
        source="synthetic",
        complete=complete,
    )


def test_closed_session_withholds_live_levels() -> None:
    director = Director()
    director.set_session(True, 600000)
    director.observe(candle(0, complete=False), [], 1000)
    frame = director.view(1000)
    assert frame.hook.kind == "SESSION_OPEN"
    assert frame.hook.countdown_ms == 599000
    assert frame.session == "Market closed" and not frame.levels and not frame.marks
    director.set_session(False)
    director.observe(candle(600000, complete=False), [], 600001)
    assert director.view(600001).levels


def test_only_falsifiable_calls_score_and_results_never_disappear() -> None:
    director = Director()
    director.ingest("comment", "Viewer", "UP", 1000)
    director.observe(candle(60000, complete=False), [candle(0)], 60001)
    assert not director.view(60001).scoreboard.rows
    for index in range(110):
        start = index * 420000
        call = Call(created_ms=start, kind="SETUP", direction="LONG", entry_lo=100,
                    entry_hi=100, invalidation=99, target=105, expires_ms=start+360000,
                    state_hash=f"state-{index}", reason="Synthetic falsifiable call",
                    symbol="XAUUSD", clock_version=1)
        director.create_call(call)
        director.create_call(call)
        CallResolver(director.ledger, .01).evaluate(call.id, [candle(start)],
                                                   start+60000, clock_version=1)
    frame = director.view(110*420000)
    assert frame.scoreboard.all_time.losses == 110
    assert frame.scoreboard.last_20.losses == 20
    assert len(frame.scoreboard.rows) == 110


def test_closed_market_levels_command_and_unknown_open_do_not_invent_live_prices() -> None:
    director = Director()
    director.observe(candle(0, complete=False), [], 1)
    director.set_session(True)
    director.ingest("comment", "Viewer", "!levels", 1000)
    frame = director.view(1000)
    assert frame.card and "live levels are withheld" in frame.card.answer
    assert frame.hook.id == "session:pending" and frame.hook.countdown_ms == 0


def test_score_answer_uses_the_default_window_and_shows_exclusions() -> None:
    director = Director()
    director.ingest("comment", "Viewer", "!score", 1000)
    card = director.view(1000).card
    assert card and "0W / 0L" in card.answer
    assert "0 scratch" in card.answer and "0 cancelled" in card.answer


def test_bias_answer_uses_engine_bias_without_inventing_analysis() -> None:
    director = Director()
    director.set_analysis({"H4": "BULLISH", "H1": "NEUTRAL", "M15": "BEARISH"}, [])
    director.ingest("comment", "Viewer", "!bias", 1000)
    card = director.view(1000).card
    assert card and "H4: bullish / H1: neutral / M15: bearish" in card.answer


def test_never_empty_hook_for_sixty_minute_replay() -> None:
    director = Director()
    base = 1789680000000
    previous = None
    for elapsed in range(0, 3600000, 100):
        now = base + elapsed
        bucket = now // 60000 * 60000
        bar = candle(bucket, 100 + ((elapsed // 60000) % 3) - 1, False)
        closed = (
            [candle(bucket - 60000, 100 + (((elapsed // 60000) - 1) % 3) - 1)]
            if previous != bucket
            else []
        )
        director.observe(bar, closed, now)
        frame = director.view(now)
        assert frame.hook.headline and frame.hook.sub and frame.hook.countdown_ms >= 0
        previous = bucket
    director.close(base + 3600000)
    assert any(
        row.get("kind") == "beat" and row["type"] == "hook.CANDLE_CLOSE" for row in director.timeline.rows
    )


@pytest.mark.parametrize("name", ["Amina💛", "مرحبا_ذهب", "z" * 40, "A\u202eB", "Ana👩\u200d💻"])
def test_handles_survive_unicode_and_are_capped(name: str) -> None:
    assert handle_key(name)
    assert "\u202e" not in display_handle(name)
    if name == "z" * 40:
        assert len(display_handle(name)) == 18 and display_handle(name).endswith("…")


@pytest.mark.parametrize(
    "name", ["<img src=x onerror=alert(1)>", "ORACLE_support", "ExnessAdmin", "f.u.c.k"]
)
def test_unsafe_or_impersonating_handles_never_reach_screen(name: str) -> None:
    director = Director()
    assert not director.ingest("comment", name, "!score", 0)
    assert not director.view(0).card
    assert not director.shouts


def test_malformed_unicode_cannot_break_the_timeline_and_skin_tones_stay_attached(
    tmp_path: Path,
) -> None:
    assert handle_key("\ud800") is None
    director = Director(Timeline(tmp_path / "events.jsonl"))
    assert director.ingest("comment", "Amina\ud800", "!score", 0)
    card = director.view(0).card
    assert card and card.handle == "Amina"
    assert display_handle("x" * 16 + "👍🏽" + "yz") == "x" * 16 + "👍🏽…"


def test_gamechanger_tails_only_new_submitted_events_and_partial_lines(tmp_path: Path) -> None:
    import json

    path = tmp_path / "events.jsonl"
    path.write_text('{"old":true}\n', encoding="utf-8")
    director = Director()
    tail = GamechangerTail(path)
    assert tail.poll(director, 10000) == 0
    row = {
        "kind": "event",
        "action": "submitted",
        "arrived_at": 10.1,
        "live": {"type": "comment", "name": "Amina", "text": "!score", "event_id": "1"},
    }
    data = json.dumps(row) + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(data[:25])
    assert tail.poll(director, 10200) == 0
    with path.open("a", encoding="utf-8") as stream:
        stream.write(data[25:])
    assert tail.poll(director, 10300) == 1
    assert director.view(10300).card
    assert not ingest_record(director, row, 10400)  # Duplicate event.
    row["action"] = "dropped:killed"
    assert not ingest_record(director, row, 10500)


def test_echo_is_immediate_even_when_answer_card_is_rate_limited() -> None:
    director = Director()
    director.ingest("comment", "Sara", "!score", 0)
    director.ingest("comment", "Amina", "What is gold watching?", 1000)
    frame = director.view(1100)
    assert frame.card and frame.card.handle == "Sara"
    assert frame.comment and frame.comment.handle == "Amina" and frame.comment.at_ms == 1000
    assert director.view(5000).comment is None
    assert not director.ingest("comment", "Other", "My balance is $12,345", 1000)
    assert not director.ingest("comment", "еxness_support", "!score", 1000)


def test_director_prefers_market_relevant_questions_when_answers_are_queued() -> None:
    director = Director()
    director.observe(candle(0), [], 0)
    director.ingest("comment", "First", "!score", 0)
    director.ingest("comment", "Other", "How is the weather?", 1000)
    director.ingest("comment", "Amina", "What price level is gold watching?", 1100)
    card = director.view(45000).card
    assert card and card.handle == "Amina"
    assert "verified candle" in card.answer


def test_retention_report_uses_real_samples_and_does_not_invent_missing_counts() -> None:
    rows = [
        {"kind": "viewers", "at_ms": 0, "count": 100},
        {"kind": "viewers", "at_ms": 10000, "count": 105},
        {"kind": "viewers", "at_ms": 20000, "count": 110},
        {"kind": "beat", "type": "context", "start_ms": 0, "end_ms": 20000},
        {"kind": "beat", "type": "answer", "start_ms": 40000, "end_ms": 50000},
    ]
    result = retention_report(rows)
    assert result["beats"]["context"]["average_viewer_delta"] == 10
    assert result["beats"]["answer"]["average_viewer_delta"] is None
    director = Director(Timeline())
    director.ingest("viewers", "", "", 0, viewer_count=50)
    director.view(0)
    director.view(10000)
    director.view(20000)
    director.view(30000)
    assert len([r for r in director.timeline.rows if r["kind"] == "viewers"]) == 3
