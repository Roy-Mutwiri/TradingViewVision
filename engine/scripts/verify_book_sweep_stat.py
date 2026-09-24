from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from oracle.config import load_config
from oracle.data.candle_store import CandleStore
from oracle.stats import compute_history_stats


def _copy_unlocked_store(candidates: list[Path], target: Path) -> tuple[Path, Path]:
    target.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for candidate in candidates:
        try:
            if candidate.resolve() != target.resolve():
                shutil.copy2(candidate, target)
            return candidate, target
        except PermissionError as exc:
            errors.append(f"{candidate}: {exc}")
            continue
    raise RuntimeError("No readable candle store found. " + " | ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the book sweep-follow statistic definition and samples.")
    parser.add_argument("--store", help="Optional candles.duckdb path. Defaults to the largest runtime store.")
    args = parser.parse_args()

    cfg = load_config(ROOT / "config/oracle.yaml")
    configured_store = ROOT / cfg.data.store_path
    runtime = ROOT / "runtime"
    candidates = [Path(args.store)] if args.store else sorted(
        (p for p in runtime.rglob("candles.duckdb") if p.exists()),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        candidates = [configured_store]
    proof_store = ROOT / "runtime/ui-proof/book-stats-candles.duckdb"
    store_path, proof_store = _copy_unlocked_store(candidates, proof_store)
    store = CandleStore(proof_store, cfg.data.canonical_broker)
    try:
        stats = compute_history_stats(store, cfg.data.broker_symbol_patterns[-1])
    finally:
        store.close()

    table = stats.get("sweeps", {}).get("follow_after_reclaim", {})
    out = {
        "stat_id": "stat:sweep_follow",
        "store_path": str(store_path),
        "proof_store_path": str(proof_store),
        "data_range": stats.get("data_range"),
        "n": table.get("n"),
        "counts": table.get("counts"),
        "pct": table.get("pct"),
        "definition": table.get("definition"),
        "sample_rows": (table.get("samples") or [])[:5],
    }

    target = ROOT / "runtime/ui-proof/book-sweep-follow-stat.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


