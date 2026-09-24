"""Small synthetic rulings plus real broker prefix/determinism/MSS tests."""

import hashlib, json
from collections import Counter
from pathlib import Path
import pytest
from oracle.candidates.contracts import EvalPoint
from oracle.config import LiquidityConfig, StructureConfig
from oracle.models import Bar
from oracle.smc.liquidity import LiquidityEngine, liquidity
from oracle.smc.liquidity_contracts import LiquidityGeometry, Pool
from oracle.smc.liquidity_drawing import liquidity_objects
from oracle.smc.structure import StructureState, evaluate_structure
from oracle.smc.swing_contracts import Pivot, EqualPivotPair, SwingSnapshot
from oracle.smc.swings import load_swing_config

ROOT = Path(__file__).parents[3]


def bar(i, h=101, c=99, l=98):
    return Bar(
        tf="M15",
        t_open_ms=1700000100000 + i * 900000,
        o=99,
        h=h,
        l=l,
        c=c,
        tick_volume=1,
        source="synthetic",
        complete=True,
        digits=3,
    )


def point(seq, b, phase="CLOSE", price=None):
    return EvalPoint(
        seq=seq,
        t_broker_ms=b.t_open_ms + (900000 if phase == "CLOSE" else 250),
        price=b.c if price is None else price,
        bar_index=seq,
        bar_phase=phase,
        source="BAR_COARSE",
        fidelity="BAR",
    )


def engine():
    e = LiquidityEngine("M15", LiquidityConfig(named_levels=()))
    g = LiquidityGeometry(
        tf="M15",
        direction="BEARISH",
        side="HIGH",
        name="EQH",
        level=100,
        price_lo=100,
        price_hi=100,
        ce=100,
        atr_at_creation=10,
        created_ms=bar(0).t_open_ms - 900000,
        t_start_ms=bar(0).t_open_ms - 900000,
        source_bars=(0, 1),
        source_object_ids=("pivot.one", "pivot.two"),
    )
    e.pools["pool"] = Pool(id="pool", geometry=g, strength=2)
    e.active.add("pool")
    return e


def test_equal_cluster_uses_extreme_not_mean():
    pivots = []
    for idx, value in [(2, 100), (7, 100.08)]:
        pivots.append(
            Pivot(
                tf="M15",
                idx=idx,
                t_ms=bar(idx).t_open_ms,
                price=value,
                side="HIGH",
                kind=None,
                confirmed=True,
                confirmed_at_idx=idx + 2,
                confirmed_at_ms=bar(idx + 2).t_open_ms,
                atr=1,
                leg_atr=2,
                significant=True,
                opposite_pivot_id="low",
                gap_adjacent=False,
                source_bars=(idx,),
                source_object_ids=(f"bar.{idx}",),
            )
        )
    pair = EqualPivotPair(
        kind="EQH",
        price_mean=100.04,
        pivot_ids=tuple(p.id for p in pivots),
        bar_indices=(2, 7),
        count=2,
        tolerance=0.1,
        source_object_ids=tuple(p.id for p in pivots),
    )
    e = LiquidityEngine("M15")
    e.equal_pools(
        SwingSnapshot(at_idx=9, internal=tuple(pivots), equal_pairs=(pair,), atr=(1,) * 10),
        point(9, bar(9)),
        9,
        bar(10).t_open_ms,
    )
    p = next(iter(e.pools.values()))
    assert p.level == 100.08 and p.strength == 2


@pytest.mark.parametrize("close,state,sweeps", [(99, "SWEPT", 1), (100.6, "BROKEN", 0)])
def test_wick_reclaim_vs_body_acceptance(close, state, sweeps):
    e = engine()
    b = bar(0, c=close)
    p = point(0, b)
    e.process(p, b, 0, p.t_broker_ms, 10)
    assert e.pools["pool"].state == state and len(e.sweeps) == sweeps
    assert not e.pools_above(98, "M15")
    if sweeps:
        assert e.sweeps[0].reclaim_bar_idx == 0


def test_pending_countdown_and_all_three_terminal_fades():
    traces = []
    for outcome in ("PROMOTE", "INVALIDATED", "STALE"):
        e = engine()
        b = bar(0, c=100)
        p = point(0, b, "INTRA", 101)
        e.process(p, b, 0, p.t_broker_ms, 10)
        candidate = next(iter(e.candidates.values()))
        assert candidate.state == "CANDIDATE"
        objects = liquidity_objects(e, b.t_open_ms, 100, 0)
        assert objects[0].text_args["bars_left"] == 3 and objects[0].text_args["confirmed"] is False
        for idx in range(3):
            b = bar(
                idx, c=99 if outcome == "PROMOTE" else 100.6 if outcome == "INVALIDATED" else 100
            )
            p = point(idx + 1, b)
            e.process(p, b, idx, p.t_broker_ms, 10)
            if e.candidates[candidate.id].state != "CANDIDATE":
                break
        terminal = [d for d in e.decisions if d.action in ("PROMOTE", "DISCARD")]
        assert len(terminal) == 1
        assert (
            (terminal[0].action == "PROMOTE")
            if outcome == "PROMOTE"
            else terminal[0].reason == outcome
        )
        if outcome != "PROMOTE":
            assert any(
                o.text_args.get("lifecycle") == "DISCARDED"
                and o.text_args["discard_reason"] == outcome
                for o in liquidity_objects(e, b.t_open_ms, 100, idx)
            )
        traces.extend(terminal)
    assert Counter(d.reason for d in traces) == {None: 1, "INVALIDATED": 1, "STALE": 1}


def test_sweep_and_bos_same_level_same_bar_are_exclusive():
    e = engine()
    data = [bar(i, h=100, c=99) for i in range(5)] + [bar(5, h=101, c=100.6)]
    b = data[-1]
    p = point(5, b)
    e.process(p, b, 5, p.t_broker_ms, 10)
    state = StructureState(major_high=100, major_high_idx=0, major_high_id="confirmed.high")
    event = evaluate_structure(state, data, [], 10, StructureConfig(), e.sweep_query).last_event
    assert event.kind == "BOS" and event.level == 100 and not e.sweeps


def test_mss_requires_prior_opposite_sweep_and_never_relabels():
    e = engine()
    b = bar(0)
    p = point(0, b)
    e.process(p, b, 0, p.t_broker_ms, 10)
    data = [bar(i) for i in range(6)]
    data[-1] = bar(5, h=101, c=89, l=88)
    state = StructureState(
        trend="BULLISH",
        major_low=90,
        major_low_idx=0,
        major_low_id="confirmed.low",
        protected_low=90,
    )
    event = evaluate_structure(state, data, [], 10, StructureConfig(), e.sweep_query).last_event
    assert event.is_mss and event.sweep_event_id == e.sweeps[0].id and event.kind == "CHoCH"
    assert e.sweep_query("M15", 0, 10, "DOWN") is None
    assert e.sweep_query("M15", 11, 10, "DOWN") is None
    assert e.sweep_query("M15", 5, 10, "UP") is None
    unchanged = evaluate_structure(state, data, [], 10, StructureConfig()).last_event
    assert not unchanged.is_mss
    e.sweeps = e.sweeps + (e.sweeps[0].model_copy(update={"confirmed_bar_idx": 5}),)
    assert not unchanged.is_mss and e.sweep_query("M15", 5, 10, "DOWN") == e.sweeps[0].id


def test_queries_are_sorted_and_exclude_consumed():
    e = engine()
    p = e.pools["pool"]
    for level, state in [(99, "FRESH"), (102, "TOUCHED"), (103, "SWEPT"), (98, "BROKEN")]:
        oid = str(level)
        g = p.geometry.model_copy(
            update=dict(level=level, price_lo=level, price_hi=level, ce=level)
        )
        e.pools[oid] = p.model_copy(update=dict(id=oid, geometry=g, state=state))
        e.active.add(oid)
    assert [p.level for p in e.pools_above(100, "M15")] == [102]
    assert [p.level for p in e.pools_below(100, "M15")] == [99]


def test_real_500_decisions_and_prefix_are_identical():
    d = json.loads(
        (
            ROOT / "engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json"
        ).read_text()
    )
    bars = [Bar.model_validate(b) for b in d["seed"] + d["parents"]]
    minutes = [Bar.model_validate(b) for b in d["minutes"]]
    cfg = load_swing_config(ROOT / "config/weights.yaml")
    first, cursor = liquidity(bars, minutes, swing_config=cfg)
    second, _ = liquidity(bars, minutes, swing_config=cfg)
    text = "".join(d.canonical_json() + "\n" for d in first.decisions)
    assert text == "".join(d.canonical_json() + "\n" for d in second.decisions)
    prefix, _ = liquidity(bars[:100], minutes, swing_config=cfg)
    assert [d.canonical_json() for d in first.decisions if d.seq < 100] == [
        d.canonical_json() for d in prefix.decisions
    ]
    byid = {s.id: s for s in first.sweeps}
    for event in cursor.events:
        if event.is_mss:
            s = byid[event.sweep_event_id]
            assert 0 < event.break_bar_idx - s.confirmed_bar_idx <= 10 and s.side == (
                "LOW" if event.direction == "UP" else "HIGH"
            )
    golden = ROOT / "engine/tests/fixtures/real/liquidity-ExnessKE-MT5Trial10-golden.json"
    assert golden.exists(), "regenerate: missing liquidity golden"
    if golden.exists():
        g = json.loads(golden.read_text())
        assert g["server"] == d["metadata"]["server"], "regenerate: server"
        assert g["clock_version"] == d["metadata"]["clock_version"], "regenerate: clock"
        assert (
            g["weights_hash"]
            == hashlib.sha256((ROOT / "config/weights.yaml").read_bytes()).hexdigest()
        ), "regenerate: weights"
        assert g["schema_version"] == 1 and g["structure_schema_version"] == 2, "regenerate: schema"
        assert g["config"] == LiquidityConfig().model_dump(mode="json"), "regenerate: config"
        from oracle.config import SessionsConfig

        assert g["sessions"] == SessionsConfig().model_dump(mode="json"), "regenerate: sessions"
        assert g["decisions_sha256"] == hashlib.sha256(text.encode()).hexdigest(), (
            "regenerate: liquidity"
        )
    assert first.sweeps


def test_recorded_evalpoints_reproduce_liquidity_and_census(tmp_path):
    from oracle.candidates.lifecycle import CandidateEngine
    from oracle.candidates.run import CandidateRun
    from oracle.candidates.replay import recorded
    from oracle.candidates.sources import replay_points
    from oracle.config import ZonesConfig

    d = json.loads(
        (
            ROOT / "engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json"
        ).read_text()
    )
    seed = [Bar.model_validate(b) for b in d["seed"]]
    parents = [Bar.model_validate(b) for b in d["parents"][:40]]
    minutes = [Bar.model_validate(b) for b in d["minutes"]]
    cfg = load_swing_config(ROOT / "config/weights.yaml")
    e = CandidateEngine(
        "M15",
        seed,
        ZonesConfig(),
        order_blocks_enabled=True,
        liquidity_enabled=True,
        swing_config=cfg,
    )
    meta = d["metadata"] | {
        "order_blocks_enabled": True,
        "liquidity_enabled": True,
        "structure_config": StructureConfig().model_dump(mode="json"),
        "liquidity_config": LiquidityConfig().model_dump(mode="json"),
        "swing_config": cfg.model_dump(mode="json"),
    }
    run = CandidateRun(e, tmp_path / "source", meta)
    points, _ = replay_points(parents, minutes)
    for p in points:
        b = parents[p.bar_index]
        available = [
            m
            for m in minutes
            if e.liquidity.calendar.last_ms < m.t_open_ms and m.t_open_ms + 60000 <= p.t_broker_ms
        ]
        run.process(
            p,
            parent_open_ms=b.t_open_ms,
            closed_bar=b if p.bar_phase == "CLOSE" else None,
            closed_minutes=available,
        )
        ds = [d for d in e.decisions if d.kind != "POOL"]
        counts = Counter(d.action for d in ds)
        still = (
            sum(c.state == "CANDIDATE" for c in e.candidates.values())
            + sum(c.state == "CANDIDATE" for c in e.ob.candidates.values())
            + sum(c.state == "CANDIDATE" for c in e.liquidity.candidates.values())
        )
        assert counts["CREATE"] == counts["PROMOTE"] + counts["DISCARD"] + still
    replay = recorded(run.directory, tmp_path / "replay")
    assert (run.directory / "decisions.jsonl").read_bytes() == (
        replay.directory / "decisions.jsonl"
    ).read_bytes()
    assert [s.canonical_json() for s in e.liquidity.sweeps] == [
        s.canonical_json() for s in replay.engine.liquidity.sweeps
    ]


def test_ribbon_calendar_dst_uses_shared_definitions():
    from datetime import UTC, datetime
    from oracle.data.sessions import session_intervals

    for month, ny, london in [(1, 13, 8), (7, 12, 7)]:
        t = int(datetime(2026, month, 15, tzinfo=UTC).timestamp() * 1000)
        intervals = {s.key: s for s in session_intervals(t)}
        assert (intervals["NY"].start_ms - t) // 3600000 == ny
        assert (intervals["LONDON"].start_ms - t) // 3600000 == london
        assert intervals["ASIA"].start_ms == t


def test_real_golden_is_independent_of_python_hash_seed():
    import os, subprocess, sys

    code = "from engine.tests.unit.test_liquidity import test_real_500_decisions_and_prefix_are_identical;test_real_500_decisions_and_prefix_are_identical()"
    for seed in ("1", "99"):
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=dict(os.environ, PYTHONHASHSEED=seed),
            check=True,
            capture_output=True,
            text=True,
        )


def test_running_extreme_cannot_retire_a_pending_raid():
    e = engine()
    b = bar(0, c=100)
    p = point(0, b, "INTRA", 101)
    e.process(p, b, 0, p.t_broker_ms, 10)
    c = next(iter(e.candidates.values()))
    e.retire("pool", p, p.t_broker_ms)
    assert e.candidates[c.id].state == "CANDIDATE" and "pool" in e.active
    b = bar(0, c=99)
    p = point(1, b)
    e.process(p, b, 0, p.t_broker_ms, 10)
    assert e.candidates[c.id].state == "PROMOTED" and e.pools["pool"].state == "SWEPT"
    assert not any(d.reason == "SUPERSEDED" for d in e.decisions)
