
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from oracle.config import load_config
from oracle.data.candle_store import CandleStore
from oracle.stats import compute_history_stats

parser = argparse.ArgumentParser()
parser.add_argument('--config', default='config/oracle.yaml')
parser.add_argument('--out', default='runtime/ui-proof/book-volume-1/stats-report.json')
parser.add_argument('--store', default=None)
args = parser.parse_args()
cfg = load_config(ROOT / args.config)
store_path = Path(args.store) if args.store else max((p for p in (ROOT/'runtime').rglob('candles.duckdb')), key=lambda p: p.stat().st_size, default=ROOT / cfg.data.store_path)
store = CandleStore(str(store_path), cfg.data.canonical_broker)
stats = compute_history_stats(store, cfg.data.broker_symbol_patterns[-1])
out = ROOT / args.out
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding='utf-8')
print(json.dumps({
  'out': str(out.relative_to(ROOT)),
  'store': str(store_path.relative_to(ROOT)) if store_path.is_absolute() else str(store_path),
  'id': stats.get('id'),
  'bar_count': stats.get('bar_count'),
  'data_range': stats.get('data_range'),
  'adr20': stats.get('adr20'),
  'london_takes_asia': stats.get('london_takes_asia'),
  'sweeps': stats.get('sweeps'),
  'daily_model': stats.get('daily_model'),
}, indent=2))
store.close()
