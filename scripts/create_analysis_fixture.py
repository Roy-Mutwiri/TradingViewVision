"""One-time synthetic fixture authoring; expected outcomes do not call the resolver."""

import json
from pathlib import Path

from oracle.analysis.contracts import Call

calls, bars, expected = [], [], []
for index in range(50):
    start, price = index * 420000, 100 + index * 10
    scenario = index % 5
    call = Call(created_ms=start, kind="SETUP" if index % 2 else "STRUCTURE",
                direction="LONG", entry_lo=price, entry_hi=price,
                invalidation=price - 2, target=price + 4, expires_ms=start + 360000,
                state_hash=f"fixed-state-{index}", reason=f"Synthetic scenario {scenario}",
                symbol="XAUUSD", clock_version=1)
    calls.append(call.model_dump())
    for minute in range(6):
        low, high, close = price - .5, price + .5, price
        if scenario == 4:
            low, high, close = price + 1, price + 2, price + 1.5
        elif minute == 1 and scenario in (0, 1, 2):
            low = price - 2 if scenario in (1, 2) else price - .5
            high = price + 4 if scenario in (0, 2) else price + .5
        bars.append(dict(symbol="XAUUSD", tf="M1", t_open_ms=start + minute * 60000,
                         o=close, h=high, l=low, c=close, tick_volume=1,
                         source="synthetic", complete=True, digits=3))
    expected.append(dict(id=call.id,
                         state=("WIN", "LOSS", "LOSS", "SCRATCH", "NEVER_TRIGGERED")[scenario],
                         resolved_ms=start + (120000 if scenario < 3 else 360000),
                         ambiguous=scenario == 2))
output = Path(__file__).resolve().parents[1] / "engine/tests/fixtures/analysis_calls.json"
output.write_text(json.dumps(dict(provenance="SYNTHETIC BID M1 accountability fixture, not broker proof",
                                  tick_size=.01, now_ms=21000000,
                                  calls=calls, bars=bars, expected=expected), indent=2) + "\n")
