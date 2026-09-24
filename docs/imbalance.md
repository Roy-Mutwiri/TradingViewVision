# SMC build step 1: imbalance primitive

`detect_fvg` takes exactly three ordered candles and an explicit ATR observation.
The observation is shared Wilder ATR(14) on the gap's own timeframe at c3 close.
All three must be closed. A missing ATR cannot qualify a gap. Bullish bounds
are c1.high to c3.low; bearish bounds are c3.high to c1.low. Equality of candle
edges is not a gap; equality at the configured size threshold qualifies.
CE and size are derived exactly. Frozen geometry records source indices,
bar IDs, ATR and threshold, creation time, and gap adjacency. Its exact
canonical hash does not round away sub-cent geometry changes.

`observe_fill` takes a later same-timeframe candle and previous confirmed fill.
Wicks determine cumulative fill (a fraction from zero to one). The remaining
rectangle is a projection; original bounds never change. A wholly skipped
gap supplies no wick coverage. A far-edge body close invalidates; IFVG evidence
additionally requires full traded coverage, and supplies the inverted polarity.
Far-edge equality does not invalidate. CE equality holds; a close against CE
weakens. A wick alone does not weaken or invert.

Forming candles can supply provisional fill observations for the future tick
display. They cannot confirm CE weakening, invalidation or inversion. Callers
must not commit a provisional fill as the next confirmed previous_fill.
Creation candles cannot consume their own gap. The shared Wilder ATR function
remains the only ATR implementation; the detector never estimates one.

The approved `zones` config is persisted, including the 0.20 FVG threshold.
Tests use explicitly synthetic three-candle fixtures. These are not the later
real XAUUSDz producer golden. MarketState has not changed in this step.

`FVGGeometry` and `FVGRecord` schema 3 freeze `atr_at_creation`; older records fail
validation and require regeneration. Later volatility never rechecks the gate.
`advance_fvg` creates new frozen lifecycle snapshots with stable identity.
The first confirmed CE loss latches weakening, its close timestamp and bar index;
reclaims never reset it. It remains drawable but cannot qualify an A-setup.
Full traded coverage plus a far-edge close makes the original terminal INVERTED
and creates a new opposite-polarity IFVG with its parent ID and exact inversion
reason. A failed IFVG becomes terminal INVALID and logs REINVERSION_ATTEMPT once;
no second-generation inversion can be created. Terminal records remain in history.

`ImbalanceCursor` incrementally carries the existing shared ATR implementation,
the last three closed bars, all immutable records and provenance events. Restoring
a checkpoint retains the CE latch and reproduces continuous replay. Starting
from raw truncated history without a prior checkpoint cannot recover past events.

Detection-time merging uses intersection divided by the smaller gap, strictly
greater than `fvg_merge_overlap`. Candidates sort by start time, low and ID;
union-find builds whole connected components with matching direction, timeframe
and lifecycle state. Terminal and inverse gaps cannot become original-FVG unions.
The entire component is rejected and logged if its union exceeds
`max_merged_span_atr` (2.5) times the latest constituent's frozen ATR. No pairwise
fallback is attempted.

Unions have new hashes over sorted leaf constituent IDs, preserve source bars
and object IDs, start at the earliest constituent start and are created only at
the latest constituent c3 close. Their ATR is that latest constituent's observation.
Constituents become terminal MERGED and stay in immutable history. Strength counts
leaf constituents, including when an existing union absorbs another gap.

Inherited weakening never clears and takes the earliest historical CE-loss
provenance. The union tracks `ce_lost` separately against its own midpoint from
its confirmation onward; both latches exclude A-setups. A prior union's CE loss
is also retained when that union is later absorbed, preventing merge laundering.

`merge_fvgs` requires an explicit `as_of_ms` horizon and walks stored closed bars
from `created_ms`, measuring fill against the union range. Formation candles never
contribute; a newly confirmed union starts at 0% fill. `t_start_ms` is only the
drawing anchor. No future or forming bar
can contribute. Incremental cursors retain the source history needed for this walk.
The live chart projects confirmed records through DrawObject. Gradients and CE
lines render below candles; forming-bar wicks preview fill without advancing
canonical lifecycle state. The newest three unfinished zones are retained per
timeframe. No call producer is included in this step.
