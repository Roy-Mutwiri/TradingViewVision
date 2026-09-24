"""Synthetic textbook unit fixtures; golden replay below uses real broker history."""

import ast
import json
import threading
from pathlib import Path

import pytest

from oracle.candidates.contracts import EvalPoint, decisions_hash
from oracle.candidates.lifecycle import CandidateEngine, confirmed_only
from oracle.candidates.replay import recorded, synthetic
from oracle.candidates.run import CandidateRun
from oracle.candidates.sources import LiveBuckets, replay_points, traversal
from oracle.config import OracleConfig, ZonesConfig
from oracle.data.candidate_service import CandidateService
from oracle.models import Bar

ROOT = Path(__file__).parents[3]
DATASET = ROOT/"engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json"
BASE = 1700000100000


def bar(index, *, o=100, h=102, l=98, c=100, tf="M15"):  # noqa: E741
    return Bar(tf=tf, t_open_ms=BASE+index*900000, o=o, h=h, l=l, c=c,
               tick_volume=1, complete=True, source="synthetic", digits=3)


def engine():
    return CandidateEngine("M15", [bar(i) for i in range(14)], ZonesConfig())


def point(seq, price, phase="INTRA", index=0):
    at = BASE+(14+index)*900000+(900000 if phase=="CLOSE" else seq*250)
    return EvalPoint(seq=seq, t_broker_ms=at, price=price,
                     bar_index=index, bar_phase=phase, source="LIVE_TICK", fidelity="TICK")


def test_bucket_uses_last_tick_and_has_one_true_close():
    bucket = LiveBuckets()
    for t in range(40):
        assert not bucket.ingest(1000+t*5, 100+t, 0)
    points = bucket.ingest(1250, 150, 0)
    assert len(points) == 1 and points[0].price == 139
    assert points[0].seq == 0
    ended = bucket.close(2000, 151, 0)
    assert [p.bar_phase for p in ended] == ["INTRA", "CLOSE"]
    assert ended[-1].price == 151
    with pytest.raises(ValueError, match="duplicate CLOSE"):
        bucket.close(2000, 151, 0)
    with pytest.raises(ValueError, match="late tick"):
        bucket.ingest(2001, 152, 0)


def test_premature_close_cannot_promote_or_consume_the_sequence():
    state = engine()
    opening = BASE+14*900000
    state.process(point(0,108,"OPEN"),parent_open_ms=opening)
    early = point(1,109,"CLOSE").model_copy(update={"t_broker_ms":opening+250})
    with pytest.raises(ValueError,match="true parent bar end"):
        state.process(early,parent_open_ms=opening,closed_bar=bar(14,o=108,h=110,l=106,c=109))
    assert not state.confirmed and state.last_seq == 0 and len(state.decisions) == 1
    state.process(point(1,109,"CLOSE"),parent_open_ms=opening,closed_bar=bar(14,o=108,h=110,l=106,c=109))
    assert state.confirmed


def test_candidate_changes_are_edge_triggered_and_close_only_promotes():
    state = engine()
    assert state.process(point(0, 108, "OPEN"), parent_open_ms=BASE+14*900000)[0].action == "CREATE"
    assert not state.process(point(1, 108), parent_open_ms=BASE+14*900000)
    candidate = next(iter(state.candidates.values()))
    with pytest.raises(TypeError, match="CALL_REQUIRES_CONFIRMED_OBJECT"):
        confirmed_only(candidate)
    assert not state.confirmed
    closed = bar(14, o=108, h=110, l=106, c=109)
    decisions = state.process(point(2, 109, "CLOSE"), parent_open_ms=closed.t_open_ms, closed_bar=closed)
    assert decisions[-1].action == "PROMOTE"
    assert decisions[-1].geometry.atr_at_creation > 0
    assert confirmed_only(state.confirmed[0]) == state.confirmed[0]
    frozen = state.confirmed[0].geometry.canonical_json()
    state.process(point(3, 120, "OPEN", index=1), parent_open_ms=BASE+15*900000)
    assert state.confirmed[0].geometry.canonical_json() == frozen
    with pytest.raises(ValueError, match="last point"):
        state.process(point(4, 108, index=0), parent_open_ms=closed.t_open_ms)


def test_tick_fill_is_a_read_only_projection(tmp_path):
    run = CandidateRun(engine(), tmp_path/"tick-fill", {"test": "synthetic"})
    closed = bar(14, o=108, h=110, l=106, c=109)
    run.process(point(0, 108, "OPEN"), parent_open_ms=closed.t_open_ms)
    run.process(point(1, 109, "CLOSE"), parent_open_ms=closed.t_open_ms, closed_bar=closed)
    records = [r.canonical_json() for r in run.engine.cursor.records]
    decisions = [d.canonical_json() for d in run.engine.decisions]
    before = run.drawings(closed.t_open_ms+900000)
    forming = bar(15, o=109, h=109, l=104, c=105).model_copy(update={"complete": False})
    preview = run.drawings(forming.t_open_ms+900000, display_bar=forming)
    assert before[0].text_args["fill_pct"] == 0
    assert preview[0].text_args["fill_pct"] > 0
    assert [r.canonical_json() for r in run.engine.cursor.records] == records
    assert [d.canonical_json() for d in run.engine.decisions] == decisions
    assert run.drawings(forming.t_open_ms+900000)[0].text_args["fill_pct"] == 0
    with pytest.raises(ValueError, match="provisional"):
        run.drawings(forming.t_open_ms+900000, display_bar=bar(15))


def test_worklog_observes_all_configured_timeframes_without_re_evaluating():
    first = engine()
    second = CandidateEngine("M5", [bar(i,tf="M5") for i in range(14)], ZonesConfig())
    for state in (first,second):
        state.process(point(0,108,"OPEN"),parent_open_ms=BASE+14*900000)
    service = CandidateService.__new__(CandidateService)
    service.config = OracleConfig()
    service.current_openings = {}
    service.lock = threading.Lock()
    service.status = {"state":"RUNNING"}
    service.views = {"M15":([],first.decisions),"M5":([],second.decisions)}
    original = [decisions_hash(state.decisions) for state in (first,second)]
    _, local, worklog, status = service.snapshot("M15")
    assert local == first.decisions and {d.tf for d in worklog} == {"M5","M15"}
    assert status["state"] == "RUNNING"
    assert service.snapshot("H4")[2] == worklog
    service.views = dict(reversed(list(service.views.items())))
    assert service.snapshot("M5")[2] == worklog
    assert [decisions_hash(state.decisions) for state in (first,second)] == original


def test_worklog_preserves_update_then_promotion_at_one_evalpoint():
    state = engine()
    state.process(point(0, 108, "OPEN"), parent_open_ms=BASE+14*900000)
    state.process(point(1, 108, "CLOSE"), parent_open_ms=BASE+14*900000,
                  closed_bar=bar(14, o=108, h=110, l=105, c=108))
    assert [d.action for d in state.decisions] == ["CREATE", "UPDATE", "PROMOTE"]
    assert state.decisions[-2].seq == state.decisions[-1].seq
    service = CandidateService.__new__(CandidateService)
    service.config = OracleConfig()
    service.current_openings = {}
    service.lock = threading.Lock()
    service.status = {"state": "RUNNING"}
    service.views = {"M15": ([], state.decisions)}
    original = [d.canonical_json() for d in state.decisions]
    assert service.snapshot("M15")[2] == state.decisions
    assert [d.canonical_json() for d in state.decisions] == original


@pytest.mark.parametrize("gap,reason", [(False,"INVALIDATED"),(True,"DATA_GAP")])
def test_discard_has_closed_reason_and_fade_trace(tmp_path, gap, reason):
    run = CandidateRun(engine(), tmp_path/"run", {"test": "synthetic"})
    run.process(point(0, 108), parent_open_ms=BASE+14*900000)
    result = run.process(point(1, 99), parent_open_ms=BASE+14*900000, data_gap=gap)
    assert result[0].action == "DISCARD" and result[0].reason == reason
    trace = [json.loads(line) for line in (run.directory/"render-trace.jsonl").read_text().splitlines()]
    assert len(trace) == 1 and trace[0]["reason"] == reason
    assert trace[0]["fade_ms"] == 600 and trace[0]["reason_chip"]


def test_candidate_expiry_and_failed_size_gate():
    state = engine()
    state.process(point(0, 103), parent_open_ms=BASE+14*900000)
    result = state.process(point(1, 103, index=3), parent_open_ms=BASE+17*900000)
    assert result[0].reason == "STALE"
    state = engine()
    state.process(point(0, 102.1), parent_open_ms=BASE+14*900000)
    result = state.process(point(1, 102.1, "CLOSE"), parent_open_ms=BASE+14*900000,
                           closed_bar=bar(14,o=102.1,h=102.2,l=102.05,c=102.1))
    assert result[-1].reason == "FAILED_CRITERIA" and result[-1].criterion == "FVG_SIZE"
    assert not state.confirmed


def test_missing_authoritative_close_never_creates_a_confirmed_bar():
    state = engine()
    state.process(point(0, 103), parent_open_ms=BASE+14*900000)
    before = tuple(state.closed)
    events = state.process(point(1, 103, "CLOSE"), parent_open_ms=BASE+14*900000, data_gap=True)
    assert events[-1].action == "DISCARD" and events[-1].reason == "DATA_GAP"
    assert tuple(state.closed) == before and not state.confirmed


def test_mid_candle_start_cannot_invent_a_gap_from_missing_opening_ticks():
    state = CandidateEngine("M15", [bar(i) for i in range(14)], ZonesConfig(), initial_partial_bar=True)
    assert not state.process(point(0, 110), parent_open_ms=BASE+14*900000)
    actual = bar(14, o=100, h=112, l=99, c=110)
    assert not state.process(point(1, 110, "CLOSE"), parent_open_ms=actual.t_open_ms, closed_bar=actual)
    assert not state.candidates and not state.confirmed
    events = state.process(point(2, 110, index=1), parent_open_ms=BASE+15*900000)
    assert events[0].action == "CREATE", "the next covered bar remains eligible"


def test_old_candidate_schema_requires_explicit_regeneration(tmp_path):
    old = tmp_path/"old"
    old.mkdir()
    (old/"metadata.json").write_text('{"schema_version":1}')
    (old/"seed-bars.jsonl").touch()
    with pytest.raises(ValueError, match="regenerate"):
        recorded(old, tmp_path/"new")


def test_live_and_coarse_replay_share_confirmed_geometry_at_bar_close():
    live, replay = engine(), engine()
    closed = bar(14, o=110, h=113, l=109, c=112)
    bucket = LiveBuckets()
    for at, price in ((closed.t_open_ms, 110), (closed.t_open_ms+301, 112)):
        for evalpoint in bucket.ingest(at, price, 0):
            live.process(evalpoint, parent_open_ms=closed.t_open_ms)
    for evalpoint in bucket.close(closed.t_open_ms+900000, closed.c, 0):
        live.process(evalpoint, parent_open_ms=closed.t_open_ms,
                     closed_bar=closed if evalpoint.bar_phase == "CLOSE" else None)
    points, _ = replay_points([closed], [], coarse_only=True)
    for evalpoint in points:
        replay.process(evalpoint, parent_open_ms=closed.t_open_ms,
                       closed_bar=closed if evalpoint.bar_phase == "CLOSE" else None)
    assert live.confirmed and replay.confirmed
    assert [r.geometry for r in live.confirmed] == [r.geometry for r in replay.confirmed]
    assert [d.action for d in live.decisions if d.action == "PROMOTE"] == [d.action for d in replay.decisions if d.action == "PROMOTE"]


def test_replay_order_and_missing_m1_fallback():
    parent=bar(0)
    minutes=[Bar.model_validate(parent.model_dump() | {"tf":"M1","t_open_ms":parent.t_open_ms+i*60000,
                                                        "id":"","object_hash":""}) for i in range(15)]
    points, gaps=replay_points([parent],minutes)
    assert len(points)==60 and not gaps
    assert [p.price for p in points[:4]]==[100,98,102,100]
    assert points[0].bar_phase=="OPEN" and points[-1].bar_phase=="CLOSE"
    assert sum(p.bar_phase=="CLOSE" for p in points)==1
    assert traversal(bar(0,o=101,c=99))==(101,102,98,99)
    coarse,gaps=replay_points([parent],minutes[:5]+minutes[6:])
    assert len(coarse)==4 and all(p.fidelity=="BAR" for p in coarse)
    assert gaps[0].state=="SYNTHETIC_COARSE"
    assert gaps[0].start_ms==parent.t_open_ms+300000


def test_no_lifecycle_clock_or_renderer_dependencies():
    forbidden={"time","datetime","random","tkinter","PyQt","tiktok","TikTokLive"}
    calls={"now","time","perf_counter","monotonic","requestAnimationFrame","utcnow"}
    for path in (ROOT/"engine/oracle/candidates").glob("*.py"):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                assert not {name.name.split('.')[0] for name in node.names}&forbidden
            if isinstance(node,ast.ImportFrom):
                assert (node.module or '').split('.')[0] not in forbidden
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                assert node.func.attr not in calls


def test_real_500_bar_golden_speed_and_recorded_replay(tmp_path):
    golden=json.loads((DATASET.parent/"candidates-golden.json").read_text())
    data=json.loads(DATASET.read_text())
    for key in ("schema_version","clock_version","weights_hash","server"):
        assert golden[key]==data["metadata"][key], f"regenerate: {key} mismatch"
    first=synthetic(DATASET,tmp_path/"speed1",speed=1)
    second=synthetic(DATASET,tmp_path/"speed100",speed=100)
    assert (first.directory/"decisions.jsonl").read_bytes()==(second.directory/"decisions.jsonl").read_bytes()
    assert decisions_hash(first.engine.decisions)==golden["decisions_hash"], "regenerate: candidate golden changed"
    third=recorded(first.directory,tmp_path/"recorded")
    assert decisions_hash(third.engine.decisions)==golden["decisions_hash"]
    assert (third.directory/"decisions.jsonl").read_bytes()==(first.directory/"decisions.jsonl").read_bytes()
    discards=[d for d in first.engine.decisions if d.action=="DISCARD"]
    trace=[json.loads(line) for line in (first.directory/"render-trace.jsonl").read_text().splitlines()]
    assert len(discards)==len(trace)>0
    assert {d.id for d in discards}=={t["decision_id"] for t in trace}
