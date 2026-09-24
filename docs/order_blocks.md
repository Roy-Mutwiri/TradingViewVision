# Order blocks

The pure `order_blocks(confirmed_prefix)` analysis and incremental EvalPoint owner use the same validator. Four criteria are mandatory: an opposing-body origin cluster, a 1.5 ATR displacement range, a qualifying FVG in the leg, and a real same-timeframe BOS/CHoCH inside the ten-bar origin window. All ATR values come from the shared Wilder implementation. Confirmed geometry and its ATR freeze at promotion.

Candidate records have a distinct type. They wait for structure, promote only on CLOSE, discard on an opposing break, and fail STRUCTURE when the leg deadline expires. Pre-birth rejections use a separate audit: failing ORIGIN, DISPLACEMENT or IMBALANCE must not create fictitious candidates just to make a rejection table look busy. Each live run writes `ob-rejections.jsonl`; seed-history audit has separately named files. A seed candidate still awaiting structure is recorded once as CARRY_IN at the first EvalPoint, so replay and the endpoint census include it honestly.

Wicks touch and midpoint-mitigate on any EvalPoint. Bodies break on CLOSE only. A breaker has new geometry identity, the original parent link and inverted direction; its second break is terminal INVALID. Mitigated drawings stop at their mitigation candle and expire from current display after 50 bars; records remain retained.

FVG and OB unions share connected-component overlap and the creation-horizon filter. Containment uses intersection divided by the smaller span; merging is transitive and order-independent. Same-direction/timeframe/state unions are capped at 2.5 frozen ATR. Formation candles cannot born-fill a union.

Existing DrawObject zone primitives paint OBs below candles. Candidates use dashed 45% styling and `OB? M15`; discards have mandatory 600 ms reason-chip fades. Confirmed boxes use 11% fill, touched dashed borders, mitigated 35% opacity, hatched inverted breakers and a heavier border/diamond for CHoCH validation. Independent OB/FVG caps are three per timeframe; H1/H4 overlays halve opacity. The total chip density remains ten.

The real ExnessKE-MT5Trial10 500-bar golden pins broker server, clock, OB schema, weights and configuration. Live and recorded integrated tests check exact audit replay and candidate census. Liquidity, MSS activation, trade construction and producer integration remain outstanding; external January/July clock correlation remains unproven.
