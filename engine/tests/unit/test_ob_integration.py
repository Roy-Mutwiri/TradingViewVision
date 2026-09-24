"""One EvalPoint log owns both lifecycles, including startup carry-in objects."""

import json
from collections import Counter
from pathlib import Path
import threading
from oracle.candidates.lifecycle import CandidateEngine
from oracle.candidates.replay import recorded
from oracle.candidates.run import CandidateRun
from oracle.candidates.sources import replay_points
from oracle.config import OracleConfig, ZonesConfig
from oracle.models import Bar,DrawObject,Point,Style,DataQuality
from oracle.data.candidate_service import CandidateService
from oracle.transport.chart import ChartFrame


def test_integrated_recorded_replay_and_census(tmp_path):
    root = Path(__file__).parents[3]
    data = json.loads(
        (
            root / "engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json"
        ).read_text()
    )
    seed = [Bar.model_validate(b) for b in data["seed"]]
    parents = [Bar.model_validate(b) for b in data["parents"][:30]]
    minutes = [Bar.model_validate(b) for b in data["minutes"]]
    metadata = data["metadata"] | {
        "order_blocks_enabled": True,
        "ob_schema_version": 1,
        "zones": ZonesConfig().model_dump(mode="json"),
    }
    engine = CandidateEngine("M15", seed, ZonesConfig(), order_blocks_enabled=True)
    run = CandidateRun(engine, tmp_path / "live", metadata)
    points, _ = replay_points(parents, minutes, offset_s=metadata["offset_s"])
    for p in points:
        b = parents[p.bar_index]
        run.process(p, parent_open_ms=b.t_open_ms, closed_bar=b if p.bar_phase == "CLOSE" else None)
        for kind in ("FVG", "OB"):
            counts = Counter(d.action for d in engine.decisions if d.kind == kind)
            candidates = engine.candidates if kind == "FVG" else engine.ob.candidates
            assert counts["CREATE"] == counts["PROMOTE"] + counts["DISCARD"] + sum(
                c.state == "CANDIDATE" for c in candidates.values()
            )
    replay = recorded(run.directory, tmp_path / "recorded")
    assert (run.directory / "decisions.jsonl").read_bytes() == (
        replay.directory / "decisions.jsonl"
    ).read_bytes()
    assert (run.directory / "ob-rejections.jsonl").read_bytes() == (
        replay.directory / "ob-rejections.jsonl"
    ).read_bytes()

def test_htf_projection_refreshes_render_hash_and_preserves_geometry():
    obj=DrawObject(layer='L2',shape='ZONE',points=[Point(t_ms=1000,price=99),Point(t_ms=2000,price=101)],
        style=Style(token='zone.ob'),text_key='synthetic.fixture.ob',text_args={'tf':'H1','confirmed':True,'end_ms':3000},
        priority=4,z=0,source_bars=[0,1],confidence=1,reason='Synthetic fixture',state='FRESH',ttl_ms=0,anim={'in_':'none','loop':None})
    service=CandidateService.__new__(CandidateService)
    service.lock=threading.Lock();service.config=OracleConfig();service.status={'state':'RUNNING'}
    service.views={'M15':([],[]),'H1':([obj],[])};service.current_openings={'M15':4000}
    projected,_,_,_=service.snapshot('M15')
    assert projected[0].points==obj.points and projected[0].id==obj.id
    assert projected[0].object_hash!=obj.object_hash
    assert projected[0].text_args['overlay_opacity']==.5 and projected[0].text_args['end_ms']==4000
    frame=ChartFrame(kind='status',objects=projected,quality=DataQuality(state='OK',staleness_ms=0,spread_points=0,detail='synthetic'),
        now_ms=4000,bar_duration_ms=900000)
    assert frame.objects==projected
