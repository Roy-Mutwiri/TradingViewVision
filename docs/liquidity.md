# Liquidity and MSS

Pools, raids and reclaims use BID and the shared trading-day, trading-week and session calendar. Equal pools are derived from confirmed equal-pivot pairs and use the cluster extreme. A named running extreme receives a new immutable geometry record; a pending raid retains its original pool until its own decision resolves.

Each EvalPoint advances touches and pending sweep candidates. Only CLOSE can confirm a sweep or break a pool. Penetration ATR is frozen at candidate birth. A strictly earlier confirmed opposite-side sweep enables MSS through the injected structure hook; emitted structure events never change.

The registry supplies target queries and the Key Levels rail. SWEPT/BROKEN pools are excluded from target queries. Six pool lines, two OBs across the visible chart, one FVG and the existing ten-label placement cap keep structure readable; evicted objects remain in history. Candidate discard fades remain mandatory.

Historical statistics are in runtime/ui-proof/historical-health/baseline.md (FVG/OB) and liquidity-baseline.md (sweeps). Fixed real source: XAUUSDz, exness, ExnessKE-MT5Trial10, 2026-08-19 through 2026-09-18 UTC, stored M1 only. Goldens include server, schema, clock, weights and config metadata; mismatches require regeneration.

The real sweep STALE count is zero: timeout requires three exact-level closes because an inside close promotes and an outside close invalidates. The fixture covers exact-level timeout. The original OB 33 discards are 30 FAILED_CRITERIA(STRUCTURE), three INVALIDATED(STRUCTURE); the explicit ten-bar structure deadline explains zero generic STALE.

A restart exposed stale Friday ticks being interpreted as broker offset changes. During a known closure, a stale tick retains an existing same-server clock and never claims independent UTC verification. January/July proof remains outstanding; operator clock stays unproven.

Trade construction and producer wiring are intentionally the next steps.
