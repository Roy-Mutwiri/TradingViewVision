# Calls: construction, display and accountability

ORACLE produces analysis calls only; no code path places, modifies or closes an order. Calls use BID consistently for charting and M1 resolution.

A call is created only at a confirmed parent-bar close. Its immutable record freezes the entry zone, invalidation, TP1, optional TP2, deadline, timeframe, OTE tag, state hash, OB ID, validating structure-event ID, target-pool ID and source bars. The dealing range is `[protected_low, major_high]` in bullish structure and `[major_low, protected_high]` in bearish structure. Undefined structure, long entries at/above equilibrium and short entries at/below equilibrium are rejected.

The entry is a qualifying OB/FVG intersection of at least 0.10 ATR, otherwise the OB. Stops use the far edge plus 0.15 ATR, expanded to a linked sweep extreme, capped at 2 ATR. Targets come only from fresh/touched pool-registry entries 0.5–10 ATR away. TP1 must provide at least 1.5R; TP2 is display-only.

The shared coordinator permits at most two open calls, one direction per timeframe, and no opposing calls. A higher-timeframe setup may cancel only an opposing lower-timeframe PENDING call; ACTIVE calls remain irrevocable and suppress the new setup. A losing OB ID is permanently spent.

The append-only ledger fsyncs live events. The resolver evaluates complete BID M1 intervals, excluding partial creation/expiry minutes. Wick touches count, target+invalidation ambiguity is LOSS, and genuine missing tradeable coverage is VOID_DATA. Verified closures are skipped. SCRATCH, NEVER_TRIGGERED, CANCELLED and VOID_DATA remain visible but do not inflate hit rate.

On-chart drawings use the existing DrawObject path: bright entry zone, red SL, green TP1, dashed green TP2, live R and equal-duration WIN/LOSS outcomes. The reason strip uses the frozen reason chain for 20 seconds.

The acceptance replay reads the fixed ExnessKE-MT5Trial10 stored-M1 window from 2026-08-19 through 2026-09-18. `runtime/ui-proof/call-backtest/` contains its immutable ledger, summary and recorded M15 proof frame. A second independent run must have the same ledger SHA-256.
