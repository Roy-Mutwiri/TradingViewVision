# Falsifiable analysis calls

The engine module `oracle.analysis` separates immutable call terms from lifecycle
events. `CallLedger` writes creation, coverage progress, cancellation and resolution
as new JSONL records, flushes them to disk, and restores projections on reopening.
Targets, invalidation, deadlines, MarketState hashes and clock provenance never
change. Calls without the three required terms fail validation before recording.

`CallResolver` accepts same-symbol, same-clock-version **BID M1** OHLC data only.
It evaluates complete bars chronologically, including wicks, with half the supplied
instrument tick size as its equality tolerance. Display timeframe is irrelevant.
If both exits touch in an active bar, LOSS wins and a separate AMBIGUOUS event
records the occurrence. A later outage cannot rewrite a resolved losing call.
Missing chronological M1 coverage or an overlapping STALE/GAPPED quality interval
creates VOID_DATA with the missing interval or quality reason in the ledger.
Conflicting duplicate coverage is rejected instead of selecting favourable data.

Cancellation appends a terminal CANCELLED snapshot and a CANCEL event. It is only
legal while PENDING; ACTIVE and terminal calls raise CALL_ACTIVE_CANNOT_CANCEL.
Reasons are restricted to SUPERSEDED_BY_NEW_ANALYSIS,
STRUCTURE_INVALIDATED_BEFORE_ENTRY, EVENT_EMBARGO, DATA_DEGRADED and OPERATOR_CANCELLED.
Changed analysis after entry requires a new call; the original resolves independently.

Excursions currently use the observed active M1 bar envelopes relative to entry
midpoint and initial risk. They describe OHLC evidence; M1 data cannot establish
the order of extrema inside activation or resolution minutes.

Scoring includes only wins and losses in hit rate and expectancy. A win pays the
frozen target distance divided by midpoint-to-invalidation risk; a loss pays -1R.
Scratch, never-triggered, void and cancelled counts remain distinct in projections.
The last-20 window uses the last 20 terminal resolutions, and the all-time board
preserves every row. TODAY uses the same `data.analytical_days.trading_day` function
as the daily levels, configured by sessions.day_boundary. Membership is the
resolution day; both creation and resolution days are stored on snapshots.
The default label is “TODAY · from 17:00 NY”. ZoneInfo handles US DST.
There is no Brier score or invented probability.

## Integration and edge rules

Only complete M1 intervals within the call's life are evaluated. eval_from_ms and
eval_to_ms are frozen on creation. Activation-bar target only wins, invalidation
only loses, and both exits lose with ambiguity recorded. A zone-spanning range
enters; a range entirely past it does not. Gaps across the zone record gap_skipped.
Known calendar/session closures are skipped, not counted as data failure.

Creation rejects missing terms, invalid geometry and insufficient life before
writing to disk. retention.min_call_life_ms defaults to 300000; life must be
strictly greater. Geometry rejection is CALL_GEOMETRY_INVALID and short life is
CALL_LIFE_TOO_SHORT.

An independent worker thread reads M1 through its own history connection without
MT5 calls or display-timeframe dependence. Observed feed staleness and genuine
M1 coverage gaps create VOID_DATA with specific reasons and intervals. Display-TF
gaps do not void M1 calls. Records persist in account-scoped analysis-calls.jsonl.
The worker uses the existing data.grace_ms ingestion interval before treating a
completed minute as missing, and retains observed stale intervals after recovery.

Studio defaults to LAST 20 and offers TODAY and ALL TIME within the existing
scoreboard panel. Scratch, never-triggered, cancelled and void-data counts stay
beside the hit rate. ALL TIME exposes every ledger record; open calls remain
visible in the other windows. The displayed resolved denominator is wins + losses.
The old arbitrary result recorder is removed; producers use Director.create_call.
The SMC producer remains a scaffold, so this integration invents no predictions.

## Evidence

`engine/tests/fixtures/analysis_calls.json` freezes 50 synthetic call records,
300 fixed BID M1 bars, and an independently specified resolution set. Six-minute
call lives reflect the five-minute minimum ruling. It is
mathematical regression evidence, not broker or live-stream proof. Run:

```powershell
.\.venv312\Scripts\python.exe -m pytest engine/tests/unit/test_analysis_calls.py -q
```
