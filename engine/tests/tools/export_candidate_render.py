"""Export real-history DrawPlans for the renderer's deterministic discard checks."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from oracle.candidates.lifecycle import CandidateEngine
from oracle.candidates.run import CandidateRun
from oracle.candidates.sources import replay_points
from oracle.config import ZonesConfig
from oracle.models import Bar


def main() -> None:
    fixture = json.loads(Path("engine/tests/fixtures/real/candidates-ExnessKE-MT5Trial10-M15-500.json").read_text())
    meta = fixture["metadata"]
    parents = [Bar.model_validate(b) for b in fixture["parents"]]
    points, _ = replay_points(parents, [Bar.model_validate(b) for b in fixture["minutes"]], offset_s=meta["offset_s"])
    destination = Path("runtime/ui-proof/render-replay.jsonl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="oracle-candidate-render-") as temporary:
        engine = CandidateEngine(meta["tf"], [Bar.model_validate(b) for b in fixture["seed"]],
                                 ZonesConfig.model_validate(meta["zones"]), offset_s=meta["offset_s"])
        run = CandidateRun(engine, Path(temporary)/"audit", meta)
        with destination.open("w", encoding="utf-8") as output:
            for point in points:
                parent = parents[point.bar_index]
                decisions = run.process(point, parent_open_ms=parent.t_open_ms,
                                        closed_bar=parent if point.bar_phase=="CLOSE" else None)
                if decisions:
                    output.write(json.dumps(dict(at=point.t_broker_ms-points[0].t_broker_ms,
                                                 decisions=[d.model_dump(mode="json") for d in decisions],
                                                 objects=[o.model_dump(mode="json") for o in run.drawings(point.t_broker_ms-meta["offset_s"]*1000)]))+"\n")
    print("Real 500-bar renderer fixture exported.")


if __name__ == "__main__":
    main()
