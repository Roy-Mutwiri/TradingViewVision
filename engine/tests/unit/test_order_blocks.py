"""Explicit synthetic lifecycle corners and real demo-server determinism."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from random import Random

import pytest
from pydantic import ValidationError
from oracle.candidates.contracts import EvalPoint
from oracle.config import StructureConfig, ZonesConfig
from oracle.models import Bar
from oracle.smc.ob_contracts import OBGeometry, OBRecord
from oracle.smc.ob_drawing import ob_objects
from oracle.smc.order_blocks import advance_ob, merge_order_blocks, order_blocks

ROOT = Path(__file__).parents[3]


def real():
    d = json.loads(
        (
            ROOT / "engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json"
        ).read_text()
    )
    return d, [Bar.model_validate(b) for b in d["seed"] + d["parents"]]


def bar(i, o=100, h=102, l=98, c=101):
    return Bar(
        tf="M15",
        t_open_ms=1700000100000 + i * 900000,
        o=o,
        h=h,
        l=l,
        c=c,
        tick_volume=1,
        source="synthetic",
        complete=True,
        digits=2,
    )


def point(seq, b, phase="CLOSE"):
    return EvalPoint(
        seq=seq,
        t_broker_ms=b.t_open_ms + (900000 if phase == "CLOSE" else 250),
        price=b.c,
        bar_index=seq,
        bar_phase=phase,
        source="BAR_COARSE",
        fidelity="BAR",
    )


def record(lo=99, hi=101, index=2):
    g = OBGeometry(
        tf="M15",
        direction="BULLISH",
        price_lo=lo,
        price_hi=hi,
        ce=(lo + hi) / 2,
        size=hi - lo,
        atr_at_creation=2,
        created_ms=bar(index).t_open_ms + 900000,
        t_start_ms=bar(0).t_open_ms,
        created_idx=index,
        origin_idx=0,
        leg_start_idx=1,
        boundary="body_to_wick",
        displacement_atr=2,
        source_bars=(0, 1, 2),
        source_object_ids=(bar(0).id, bar(1).id, bar(index).id),
        fvg_ids=("synthetic.fixture.fvg",),
    )
    return OBRecord(
        geometry=g, validated_by_event_id="synthetic.fixture.bos", validation_kind="BOS"
    )


def test_wick_touch_midpoint_mitigation_and_close_only_breaker():
    r = record()
    cfg = ZonesConfig()
    original = r.geometry
    b = bar(3, o=104, h=105, l=100.5, c=104)
    r, child = advance_ob(r, point(0, b, "INTRA"), b, cfg, b.t_open_ms + 250)
    assert r.state == "TOUCHED" and child is None
    b = bar(3, o=104, h=105, l=100, c=104)
    r, _ = advance_ob(r, point(1, b, "INTRA"), b, cfg, b.t_open_ms + 500)
    assert r.state == "MITIGATED" and r.geometry == original
    b = bar(4, o=100, h=101, l=97, c=98)
    same, child = advance_ob(r, point(2, b, "INTRA"), b, cfg, b.t_open_ms + 250)
    assert child is None and same.state == "MITIGATED"
    parent, child = advance_ob(same, point(3, b), b, cfg, b.t_open_ms + 900000)
    assert parent.state == "INVALID" and child.state == "BREAKER"
    assert child.id != r.id and child.parent_id == r.id and child.geometry.direction == "BEARISH"
    b = bar(5, o=100, h=104, l=99, c=103)
    dead, grandchild = advance_ob(child, point(4, b), b, cfg, b.t_open_ms + 900000)
    assert dead.state == "INVALID" and grandchild is None
    with pytest.raises(ValidationError):
        r.geometry.price_lo = 0


def test_union_formation_is_not_a_fill_and_graph_is_order_independent():
    rs = [record(99, 100.5, 2), record(99.5, 101, 3), record(100, 101.5, 4)]
    cfg = ZonesConfig(ob_merge_overlap=0.3)
    history = [bar(i, h=110, l=90) for i in range(5)]
    merged, _ = merge_order_blocks(rs, history, cfg)
    live = [r for r in merged if r.state != "MERGED"]
    assert len(live) == 1 and live[0].state == "FRESH"
    assert len(live[0].geometry.constituent_ids) == 3 and live[0].geometry.ce == 100.25
    assert live[0].geometry.created_ms == rs[-1].geometry.created_ms
    rng = Random(7)
    expected = [r.canonical_json() for r in merged]
    for _ in range(100):
        shuffled = list(rs)
        rng.shuffle(shuffled)
        got, _ = merge_order_blocks(shuffled, history, cfg)
        assert [r.canonical_json() for r in got] == expected
    later = bar(5, h=103, l=100, c=102)
    got, _ = merge_order_blocks(rs, [*history, later], cfg)
    assert [r for r in got if r.state != "MERGED"][0].state == "MITIGATED"


@pytest.mark.parametrize("criterion", ["ORIGIN", "DISPLACEMENT", "IMBALANCE", "STRUCTURE"])
def test_each_failed_criterion_rejects_without_promotion(criterion):
    _, bs = real()
    cfg = ZonesConfig()
    struct = StructureConfig()
    if criterion == "ORIGIN":
        bs = [bar(i, o=100, h=102, l=99, c=101) for i in range(25)]
    if criterion == "DISPLACEMENT":
        cfg = ZonesConfig(ob_displacement_atr=100)
    if criterion == "IMBALANCE":
        cfg = ZonesConfig(fvg_min_atr=100)
    if criterion == "STRUCTURE":
        struct = StructureConfig(min_break_atr=100)
    engine = order_blocks(bs, cfg, struct)
    assert any(r.get("criterion") == criterion for r in engine.rejections)
    assert not any(d.action == "PROMOTE" for d in engine.decisions)


def test_real_500_bar_determinism_census_and_real_event_validation():
    meta, bs = real()
    first = order_blocks(bs)
    second = order_blocks(bs)
    text = "".join(d.canonical_json() + "\n" for d in first.decisions)
    assert text == "".join(d.canonical_json() + "\n" for d in second.decisions)
    counts = Counter(d.action for d in first.decisions)
    assert counts["CREATE"] == counts["PROMOTE"] + counts["DISCARD"] + sum(
        c.state == "CANDIDATE" for c in first.candidates.values()
    )
    assert any(d.criterion == "STRUCTURE" and d.action == "DISCARD" for d in first.decisions)
    events = {e.id: e for e in first.structure.events}
    for r in first.records:
        e = events[r.validated_by_event_id]
        g = r.geometry
        assert (
            e.timeframe == g.tf
            and e.direction == ("UP" if g.direction == "BULLISH" else "DOWN")
            or r.parent_id
        )
        assert g.origin_idx < e.break_bar_idx <= g.origin_idx + 10
    objects = ob_objects(first, bs[-1].t_open_ms + 900000)
    assert sum(o.text_args["confirmed"] for o in objects) <= 3
    golden = json.loads(
        (
            ROOT / "engine/tests/fixtures/real/order-blocks-ExnessKE-MT5Trial10-golden.json"
        ).read_text()
    )
    assert golden["server"] == meta["metadata"]["server"] == "ExnessKE-MT5Trial10", (
        "regenerate: server"
    )
    assert golden["clock_version"] == meta["metadata"]["clock_version"], "regenerate: clock"
    assert golden["schema_version"] == 1, "regenerate: OB schema"
    assert (
        golden["weights_hash"]
        == hashlib.sha256((ROOT / "config/weights.yaml").read_bytes()).hexdigest()
    ), "regenerate: weights"
    assert golden["config"] == ZonesConfig().model_dump(mode="json"), "regenerate: zones config"
    assert golden["decisions_sha256"] == hashlib.sha256(text.encode()).hexdigest(), (
        "regenerate: OB decisions"
    )


def test_prefix_causality():
    _, bs = real()
    long = order_blocks(bs[:150])
    short = order_blocks(bs[:100])
    assert [d.canonical_json() for d in long.decisions if d.seq < 100] == [
        d.canonical_json() for d in short.decisions
    ]
