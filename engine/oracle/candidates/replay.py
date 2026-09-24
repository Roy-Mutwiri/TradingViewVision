"""Offline candidate replay. Speed is presentation metadata, never lifecycle input."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from oracle.candidates.contracts import CANDIDATE_SCHEMA_VERSION, EvalPoint, decisions_hash
from oracle.candidates.lifecycle import CandidateEngine
from oracle.candidates.run import CandidateRun
from oracle.candidates.sources import replay_points
from oracle.config import LiquidityConfig, SessionsConfig, StructureConfig, ZonesConfig
from oracle.models import Bar
from oracle.smc.imbalance import FVGGeometry, FVGRecord
from oracle.smc.swings import SwingConfig


def recorded(directory: Path, output: Path) -> CandidateRun:
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    seed = [
        Bar.model_validate_json(line)
        for line in (directory / "seed-bars.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if metadata["schema_version"] != CANDIDATE_SCHEMA_VERSION:
        raise ValueError("regenerate: candidate schema mismatch")
    if (
        metadata.get("fvg_schema_version") != FVGGeometry.model_fields["schema_version"].default
        or metadata.get("fvg_record_schema_version")
        != FVGRecord.model_fields["schema_version"].default
    ):
        raise ValueError("regenerate: FVG schema mismatch")
    engine = CandidateEngine(
        metadata["tf"],
        seed,
        ZonesConfig.model_validate(metadata["zones"]),
        ttl_bars=metadata["candidate_ttl_bars"],
        offset_s=metadata["offset_s"],
        initial_partial_bar=metadata.get("initial_partial_bar", False),
        order_blocks_enabled=metadata.get("order_blocks_enabled", False),
        structure_config=StructureConfig.model_validate(metadata.get("structure_config", {})),
        swing_config=SwingConfig.model_validate(metadata.get("swing_config", {})),
        liquidity_enabled=metadata.get("liquidity_enabled", False),
        liquidity_config=LiquidityConfig.model_validate(metadata.get("liquidity_config", {})),
        sessions_config=SessionsConfig.model_validate(metadata.get("sessions_config", {})),
        seed_minutes=[Bar.model_validate_json(line) for line in (directory / "seed-minutes.jsonl").read_text().splitlines()] if metadata.get("liquidity_enabled") else [],
    )
    run = CandidateRun(engine, output, metadata)
    contexts = {
        row["seq"]: row
        for row in (
            json.loads(line)
            for line in (directory / "contexts.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    for line in (directory / "evalpoints.jsonl").read_text(encoding="utf-8").splitlines():
        point = EvalPoint.model_validate_json(line).model_copy(update={"source": "RECORDED"})
        context = contexts[point.seq]
        closed = Bar.model_validate(context["closed_bar"]) if context["closed_bar"] else None
        run.process(
            point,
            parent_open_ms=context["parent_open_ms"],
            closed_bar=closed,
            data_gap=context["data_gap"],
            closed_minutes=[Bar.model_validate(b) for b in context.get("closed_minutes", [])],
        )
    return run


def synthetic(
    dataset: Path, output: Path, *, bars: int = 500, coarse: bool = False, speed: int = 1
) -> CandidateRun:
    data: dict[str, Any] = json.loads(dataset.read_text(encoding="utf-8"))
    metadata = data["metadata"]
    if metadata["schema_version"] != CANDIDATE_SCHEMA_VERSION:
        raise ValueError("regenerate: candidate schema mismatch")
    if (
        metadata.get("fvg_schema_version") != FVGGeometry.model_fields["schema_version"].default
        or metadata.get("fvg_record_schema_version")
        != FVGRecord.model_fields["schema_version"].default
    ):
        raise ValueError("regenerate: FVG schema mismatch")
    weights = Path("config/weights.yaml")
    if (
        weights.exists()
        and hashlib.sha256(weights.read_bytes()).hexdigest() != metadata["weights_hash"]
    ):
        raise ValueError("regenerate: weights hash mismatch")
    seed = [Bar.model_validate(bar) for bar in data["seed"]]
    parents = [Bar.model_validate(bar) for bar in data["parents"][:bars]]
    minutes = [Bar.model_validate(bar) for bar in data["minutes"]]
    engine = CandidateEngine(
        metadata["tf"],
        seed,
        ZonesConfig.model_validate(metadata["zones"]),
        ttl_bars=metadata["candidate_ttl_bars"],
        offset_s=metadata["offset_s"],
    )
    run = CandidateRun(engine, output, metadata)
    points, spans = replay_points(
        parents, minutes, offset_s=metadata["offset_s"], coarse_only=coarse
    )
    (output / "coarse-spans.jsonl").write_text(
        "".join(s.canonical_json() + "\n" for s in spans), encoding="utf-8"
    )
    for point in points:
        parent = parents[point.bar_index]
        run.process(
            point,
            parent_open_ms=parent.t_open_ms,
            closed_bar=parent if point.bar_phase == "CLOSE" else None,
        )
    summary = dict(
        decisions_hash=decisions_hash(engine.decisions),
        bars=len(parents),
        speed=speed,
        coarse_spans=len(spans),
        decisions=len(engine.decisions),
        confirmed=len(engine.confirmed),
        server=metadata["server"],
    )
    (output / "summary.json").write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--recorded", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bars", type=int, default=500)
    parser.add_argument("--speed", type=int, choices=(1, 100), default=1)
    parser.add_argument("--source", choices=("m1_synth", "bar_coarse"), default="m1_synth")
    args = parser.parse_args()
    if args.recorded:
        run = recorded(args.recorded, args.output)
    elif args.dataset:
        run = synthetic(
            args.dataset,
            args.output,
            bars=args.bars,
            coarse=args.source == "bar_coarse",
            speed=args.speed,
        )
    else:
        parser.error("pass --dataset or --recorded")
    print(
        json.dumps(
            dict(
                decisions_hash=decisions_hash(run.engine.decisions),
                decisions=len(run.engine.decisions),
                output=str(args.output),
            )
        )
    )


if __name__ == "__main__":
    main()
