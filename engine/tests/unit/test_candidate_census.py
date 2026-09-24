"""A bounded recording is right-censored, not a lost-candidate bucket."""

from collections import Counter
import json
from collections import defaultdict
import pytest
from pathlib import Path

from oracle.candidates.contracts import EvalPoint
from oracle.candidates.lifecycle import CandidateEngine
from oracle.candidates.sources import replay_points
from oracle.config import ZonesConfig
from oracle.models import Bar

ROOT = Path(__file__).parents[3]


@pytest.mark.parametrize('tf',['M15','M5'])
def test_real_replay_census_and_fvg_ttl_horizon(tf):
    data = json.loads(
        (
            ROOT / "engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json"
        ).read_text()
    )
    seed = [Bar.model_validate(b) for b in data["seed"]]
    parents = [Bar.model_validate(b) for b in data["parents"]]
    minutes = [Bar.model_validate(b) for b in data["minutes"]]
    if tf=='M5':
        groups=defaultdict(list)
        for b in minutes: groups[b.t_open_ms//300000*300000].append(b)
        bs=[]
        for opening,g in sorted(groups.items()):
            if len(g)!=5: continue
            g.sort(key=lambda b:b.t_open_ms)
            bs.append(Bar(tf='M5',t_open_ms=opening,o=g[0].o,h=max(b.h for b in g),l=min(b.l for b in g),c=g[-1].c,
                tick_volume=sum(b.tick_volume for b in g),source='mt5',complete=True,digits=g[0].digits))
        seed,parents=bs[:14],bs[14:214]
    engine = CandidateEngine(tf, seed, ZonesConfig())
    points, _ = replay_points(parents, minutes, offset_s=data["metadata"]["offset_s"])
    for p in points:
        b = parents[p.bar_index]
        engine.process(
            p, parent_open_ms=b.t_open_ms, closed_bar=b if p.bar_phase == "CLOSE" else None
        )
        counts = Counter(d.action for d in engine.decisions)
        opened = sum(c.state == "CANDIDATE" for c in engine.candidates.values())
        assert counts["CREATE"] == counts["PROMOTE"] + counts["DISCARD"] + opened
        if p.bar_phase == "CLOSE":
            assert opened == 0  # FVG formation is decided at its own c3 close.
    assert not any(d.reason == "STALE" for d in engine.decisions)


def test_ttl_is_reachable_on_every_evalpoint_not_only_close():
    data = json.loads(
        (
            ROOT / "engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json"
        ).read_text()
    )
    seed = [Bar.model_validate(b) for b in data["seed"]]
    engine = CandidateEngine("M15", seed, ZonesConfig())
    opening = seed[-1].t_open_ms + 900000
    price = max(b.h for b in seed[-2:]) + 10

    def p(seq, index):
        return EvalPoint(
            seq=seq,
            t_broker_ms=opening + index * 900000,
            price=price,
            bar_index=index,
            bar_phase="OPEN",
            source="BAR_COARSE",
            fidelity="BAR",
        )

    engine.process(p(0, 0), parent_open_ms=opening)
    original = next(iter(engine.candidates))
    engine.process(p(1, 3), parent_open_ms=opening + 2700000)
    assert engine.candidates[original].state == "DISCARDED"
    assert any(d.object_id == original and d.reason == "STALE" for d in engine.decisions)
