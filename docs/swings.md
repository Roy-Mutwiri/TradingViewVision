# Phase 2a: causal swing primitive

`smc/swings.py` exposes pure `swings(prefix)`, `swing_stream(bars)` and
`advance_swings(cursor, bar)` functions. The incremental cursor is frozen;
the new step reuses prior ATR and pivot calculations. A final forming bar can
be replaced with its latest version without counting it twice in ATR.
Parameters load from the `swings` mapping in `config/weights.yaml`.

Both layers use the same 2-left/2-right wick geometry. A high must strictly
exceed its left neighbours and be greater than or equal to its right
neighbours. A low mirrors those comparisons. The first bar of a plateau
therefore wins. Confirmation requires two **closed** right bars; the output
records both pivot and confirmation indices and all five source-bar IDs.
Provisional pivots are visible in their own collection, never in confirmed
structure inputs or qualified call inputs. No structure detector is implemented
in this checkpoint.

The existing `indicators.ut_bot.rma_atr` now accepts an immutable carry and
can return its new carry. This is the only Wilder recurrence; the original
batch signature and UT Bot golden results remain unchanged. Structure uses
ATR(14) on the pivot's own timeframe and samples ATR at the pivot bar.
ATR warmup is represented by `None`; it cannot establish significance or
an ATR-tolerance pool. A forming candle does not advance structure ATR.

Every confirmed fractal remains internal. Leg size is the absolute distance
from the preceding opposite internal pivot, divided by pivot-time ATR.
Major pivots pass the configured threshold and alternate sides. A consecutive
major high replaces the previous high only if higher; a low only if lower.
Demoted pivots remain internal and earlier snapshots remain unchanged.
Labels compare the preceding same-side pivot within the corresponding layer;
seeds and equal prices remain unclassified.

Equal confirmed pivots emit EQH/EQL pools with member IDs, indices, mean
price and count, including third and later members. Equality uses the new
pivot's ATR times `eq_tolerance_atr`. Gap-adjacent pivots remain present,
with a flag when their preceding timestamp interval exceeds the timeframe.
Monthly calendar bars are rejected explicitly rather than assigned a guessed
fixed duration.

Small hand-built fixtures live under `engine/tests/fixtures/synthetic`.
The truncation harness checks all 5,000 prefixes against the corresponding
immutable snapshot from one causal full pass. These are unit tests, not the
real-history producer golden requested for section 1a. No MarketState schema
has changed yet; SetupEvidence and its schema bump follow the primitives.

The requested plateau liquidity-pair representation is awaiting clarification:
the asymmetric geometry produces one actual pivot for three adjacent equal
highs/lows, whereas an actual equal-pivot pair requires two pivot IDs.
No plateau touch is silently fabricated as a second confirmed pivot.
