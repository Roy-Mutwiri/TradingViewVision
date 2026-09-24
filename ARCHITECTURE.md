# Architecture and phase gates

Python is headless. React/Electron renders typed contracts, with no broker access
or price calculation. No order execution is allowed. Phase-2 SMC will be pure OHLC
functions. LLMs and decorative FX cannot influence geometry.

| Layer | Responsibility | Phase |
|---|---|---|
| L0 | Theme/session backdrop | 3 |
| L1 | IChartCore, exact price/time transforms | 3 |
| L2 | Justified annotations | 3 |
| L3 | Stroke/pulse/sweep/heat/camera | 4 |
| L4 | Bias/scenarios/intel/scoreboard/status | 5 |
| L5 | Seven-language subtitles, Arabic RTL | 5 |

IChartCore isolates chart vendors. Advanced Charts requires its licence and is not
bundled here. Optional TradingView mirror is never load-bearing.

## Contracts

engine/oracle/models.py defines all wire fields. Pydantic v2 rejects unknown fields,
nonfinite numbers, invalid OHLC/spreads, probabilities without samples, invalid draw
provenance and conflicting operations. Timestamps are integer UTC milliseconds.
Prices are positive finite floats. Broker-clock and session-calendar logic belongs to Phase 1.

BLAKE2b (8-byte digest) uses UTF-8 JSON, sorted keys, compact separators and no
NaNs, with floats rounded to instrument digits before hashing. Identity hashes
cover immutable fields; render hashes additionally cover mutable content.
Lifecycle transitions return new frozen objects with the same identity. State
hashes cover sorted object hash pairs, the current price tick bucket, quality,
and active segment, with no clock-version provenance.

The authoritative broker is Exness. Raw MT5 wall-clock epochs stay in the data
layer, keyed by broker/timeframe/raw open. A versioned BrokerClock maps them to
UTC and can rebuild projections without losing the original times. Historical
transition derivation uses observed closures and independent UTC OHLC alignment,
not a presumed EU/US DST calendar. Golden headers and calendar artifacts carry
clock provenance; total-coverage spans always position history and label
confidence as MEASURED, DERIVED or ASSUMED. Confidence never gates charting or
analysis. ClockRefined rebuilds projections from raw times and refetches Studio;
provisional goldens fail explicitly with a regeneration message. January and
July vendor correlation proofs are required before the real Phase 1 replay gate.

Analytical days roll at 17:00 America/New_York and midnight reference opens at
00:00 America/New_York. M1 supplies all daily/weekly reference levels; broker
D1/W1 candles are HTF structure inputs only. Session zones use zoneinfo.

Frozen models do not freeze nested containers: never mutate lists or dictionaries;
revalidate serialized input at transport boundaries.

Generated schema/TypeScript are committed; build rejects drift. Runtime WebSocket
validation belongs to Phase 3. TypeScript types alone cannot validate JSON.
Bounded bus queues fail overflow before any subscriber receives the event. No silent
drop. ReplayClock never reads wall time. JSONL logs cap at six 10 MB files and the
dashboard event deque caps at 100.

## Degradation matrix (future requirements)

| Failure | Behaviour |
|---|---|
| MT5 disconnected | Backup-feed chip; no new setups |
| Both feeds stale >15s | Freeze drawings; holding script without prices |
| Socket lost | Dim last state; reconnect visibly |
| Renderer exception | Isolate layer; keep candles |
| Event embargo | No drawings or signals |
| Intel unavailable | Status/log once; omit fact |
| Calibration degraded | Suppress probabilities |
| Resource budget exceeded | Restart at quiet window |

These are architectural requirements, not claims the foundation implements the
Director or supervisor. Distribution stays disabled until configured and authorized.
Disclaimers are localized YAML. Future modules explicitly fail if invoked.

Phase 3b's chart adapter is owned entirely by the app. The Python feed emits
frozen UTC snapshot/update/correction contracts over the authenticated worker
channel; main accepts chart IPC only from the Studio's main frame. The dedicated
MT5 gateway serializes SDK calls with tick/foreground/bulk priorities. Backfill and
calendar work own a separate DuckDB connection; brief writes share a lock while
foreground reads use snapshot isolation. Quotes use an independent throttled IPC
stream and remain live during chart work. Raw broker epochs
travel only in separate debug records. Session backgrounds use derived closures
and whitespace data. Phase 3c adds engine UT Bot DrawObject labels and optional
stop paths/colouring; indicator maths never runs in the app. Account-mode
badges stay in Studio chrome; financial account data remains absent from chart
and broadcast contracts.

Phase 4 separates operator and broadcast chrome with an F9 mode switch, without
changing native window geometry or display scaling. A private retention stream
projects engine-owned calls, moderated audience events and
an append-only scoreboard. The Director's clock is an explicit UTC-ms input;
chart positioning still passes through the existing adapter. Financial account
models are absent from retention contracts. Gamechanger input is a local JSONL
tail, independent of MT5 quote/history threads. Call reason chains are frozen
with their terms and projected verbatim through DrawObject for 20 seconds.
The Studio is permanently silent; there is no speech module or output bus.
Retention reporting uses actual viewer samples, leaving unavailable deltas null.

## Phase ownership

Phase 0: contracts/config/bus/clock/logs/dashboard shell/codegen/tests.
Phase 1: read-only MT5, ticks/M1 reconciliation, backfill, DuckDB/Parquet, quality,
replay and vendor infrastructure. Phase 2+: analysis, charts, forecast and broadcast.

Never start a phase before the preceding proof passes. Synthetic data cannot replace
30 days of broker data. During calendar bootstrap, an assumed closure template
is labeled CALENDAR_PENDING; unexplained in-session holes are GAPPED. Derived
closures come from clock-normalized M1 history and supersede that template.

References: [MT5 UTC ticks](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py),
[Pydantic schema](https://github.com/pydantic/pydantic/blob/main/docs/concepts/json_schema.md).
