# ORACLE STUDIO — Craft pass 3: a visual language, not another checklist

### Attach `oracle-reference.png` with this prompt. It is the target: same features, same layout, same window size, and the visual rules below applied.

**Scope: do not change window size, aspect ratio or scaling. Remove no features. No audio. No engine changes. Restart the app after each section and screenshot it.**

---

## 0. WHY IT STILL READS AS GENERATED

Pass 2 worked. The collisions are gone, the rail is one column, the scoreboard is a table, numerals are monospaced and the hit rate shows as a fraction. Keep all of that.

Two pass-2 acceptance checks still fail in the current frame:
- the `EXPECTANCY` row is cut off at the bottom of the rail
- the top price-axis label (`4,400`) is clipped

The bigger problem is editorial, not styling. **Every piece of data the engine produces is drawn at the same weight, in the same bordered box.** Five `BOS` labels, `MSS`, `EQL 4`, `PROTECTED` and `SWEPT` all look like identical gold-bordered buttons floating over the candles. Several different kinds of level all use the same gold line. No token system fixes that, because the problem is that nothing has been ranked.

An experienced chart developer works from a small visual language: where each kind of thing is drawn, how important it looks, and what it is allowed to be. The sections below are that language, and the reference image shows it applied to your current feature set.

---

## 1. PLACEMENT — two rules that remove almost every box from the chart

**Rule 1: levels live on the price axis.** A horizontal level is any pool, named level, protected swing or the current price. Draw it as:
- a 1px line from the bar where it formed to the price axis
- a price tag in the axis gutter
- a short uppercase name, right-aligned just above the line at the right edge of the plot

No chip, no border, no background. This is how TradingView draws horizontal levels, and viewers already know how to read it.

**Rule 2: events live at their bar.** A structure event is a dashed segment from the swing that was broken to the bar that broke it. Put a text label outside the bars' high/low range, with a halo behind it and no box. UT Bot signals are 7px triangles at the bar.

**Zone labels go at the right end of the zone, inside it.** That is the empty right-margin area where there are never any candles, so labels there cannot collide with price.

**One filled chip on the chart:** the latest UT Bot signal (`SELL` in the reference), plus the entry/SL/TP levels when a call is live. Everything else is a line plus text. Because only one thing is filled, the eye goes to the signal first.

**The text halo replaces every chip background.** Apply it to every chart label:

```css
paint-order: stroke;  stroke: var(--bg-0);  stroke-width: 3px;  stroke-linejoin: round;
```

The label stays readable over candles and grid lines without needing a box.

If a label has to move away from its anchor to avoid something (for example, the reference's `SELL` sits above the `NY H` line), draw a 1px leader line in the signal's colour back to its marker. This is the pass-2 placement rule, now used by the chip that actually needs it.

---

## 2. HIERARCHY — rank by recency and meaning

- **Structure:** show at most three events on the chart. The newest uses `--t1`, the oldest `--t2`, and CHoCH/MSS use `--acc`. **Every label includes its direction arrow**: `BOS ▲`, `MSS ▲`, `BOS ▼`. This has been in the spec since Phase 5 and is missing from the current build, where five `BOS` labels have no direction at all.
- **Each kind of line has its own style, all from the nine tokens:**

| Kind | Style |
|---|---|
| named / liquidity (PDH, NY H, EQH) | `--t1`, solid |
| swept pool | `--t2`, dashed, **stops at the sweep bar** |
| protected swing | `--acc`, solid |
| zone edges | direction tint; dashed when TOUCHED or a candidate |
| current price | direction colour, dotted |

- **Lines start at the bar where the level formed**, not at the left edge of the chart. Starting at the left edge implies the level has always existed. The one exception is prior-period levels (PDH, PDL, weekly open), which really do predate the visible range.
- **Right offset: 8 bars** (`rightOffset: 8` in Lightweight Charts). Right now about 330px to the right of the last candle is empty, and every level line stops short of the axis.
- **Check this before it goes on air:** the current frame shows `EQL 4` above current price. Equal lows above price should already be BROKEN and no longer drawn, per the liquidity spec. Either the pool state isn't updating or it's an EQH labelled as EQL. Find out which.

---

## 3. NUMBERS — one formatter, one unit

All number formatting goes through a single `fmt` module. Components never format numbers themselves.

```ts
fmt.price(v)   // 4,358.81        2dp, thousands separator: every level, zone, tag
fmt.live(v)    // 4,358.806       3dp: bid and ask only
fmt.delta(v)   // −3.21 / +12.59  signed 2dp, true minus sign U+2212
fmt.r(v)       // +1.89R
fmt.time(ms)   // 16:45           UTC, HH:MM
```

The headline bid draws its third decimal as a smaller raised digit (`4,358.80⁶`), the way broker terminals do. That is the one exception to 2dp, and it keeps the price visibly ticking.

Enforce it: `grep` fails the build on `toFixed`, `toLocaleString` or a number inside a template literal anywhere outside `fmt`.

Current defects this fixes:
- Ask shows `4358.856` with no separator while Bid shows `4,358.806`.
- Levels are 2dp and price is 3dp, with no rule for which is which.

**Unit bug — a correctness error, not styling:** `spread 50 points` uses broker points (0.001), while `0.8 points away` and `0.1 points above M15 open` use price units. The same word means two things a factor of 1,000 apart on the same screen. Use one unit: **price, in USD**. The spread shows as `0.05`, distances as `+0.10` / `−3.21`, and the Key Levels column header is `Δ USD`. The word "points" no longer appears anywhere on the broadcast surface.

**Stats gating:** below 20 resolved calls, `HIT` shows the fraction (already done) and `EXPECT.` shows `n<20`. An expectancy of `+1.89R` from a single trade misleads in exactly the same way `100%` did.

---

## 4. COPY — status text currently reads like log output

- **Labels:** uppercase nouns, two words at most.
- **Descriptions:** sentence case, six words at most, no trailing full stop.
- **All user-facing strings live in one `copy.ts`.** Components never build display text straight from engine fields.

| Now | Becomes |
|---|---|
| `No valid ENTRY / SL / TP call right now. Scanning near price.` | the gate row (§7) + `Waiting for discount · below 4,348.15` |
| `updated M5 POOL 4,360.72 – 4,360.72` | `M5 pool updated · 4,360.72` (a pool with lo = hi prints one price; this is a formatter fix, not an engine one) |
| `Live joins waiting` | the last join (`@handle joined`), or `No new joins` in `--t2` |
| `Market closed session` | `Market closed · reopens {calendar.next_open}` (read from the calendar module, never hard-coded) |
| `THE NEXT SESSION`, `THE SCOREBOARD` | drop the "THE" |
| `ALL SIGNALS RECORDED / LOSSES STAY` | `LOSSES STAY` |

**Section header meta** — the small text on the right of a rail header — is always a unit or column name (`UTC`, `Δ USD`, `SINCE`) or a live state (`SCANNING`). It is never a slogan and never a relative time like `12M AGO`. The current rail uses that slot for six different kinds of thing.

---

## 5. CHROME — boxes are only for things you can click

Grouping comes from alignment, spacing and hairline rules, not from borders.

- **Header status:** move it from the floating centre of the header into the right cluster, as a dot plus text with no pill border. This is a small layout move and the one I'm proposing in the header; veto it if you want it centred.
- **Settings:** a gear icon plus label, as a ghost button with no fill.
- **`ORACLE SCANNING FOR SIGNAL`:** the current empty bordered box looks like a text input. Make it a status line under the ask line: a dot plus the label. When a call is live it becomes `LIVE CALL · BUY 4,346.20 · SL 4,331.40 · TP1 4,366.40 · +0.7R` on the same line.
- **Timeframes and scoreboard tabs:** underline the active item instead of putting it in a filled box.
- **`+0.057` chip:** plain signed text in the direction colour.
- **Every dot gets a meaning next to text.** The dot beside `BID` is the tick indicator: it pulses on each tick and turns grey when the feed goes stale. Remove the unexplained gold dots at the far right of the price band and on the rail header, or put a label next to them.
- **Watermark:** use the UI typeface (Inter 700) at 3% opacity. The current watermark is set in a serif, a typeface used nowhere else in the app.
- **Session ribbon:** the active session gets a 1px `--acc` top edge. `NOW` is a 1px `--acc` line. Hour labels `00 06 12 18 24` sit under the bar.
- **UTC time in the watching strip:** it duplicates the clock cluster, so the reference leaves it out and puts the joins ticker in that spot. If you'd rather keep it, it goes right-aligned in `--t2`.

---

## 6. STATES — every live element needs a closed state

A countdown stuck at `00:00` looks broken, and that is what the current closed-market frame shows twice.

**Market closed:**
- `CANDLE CLOSE` shows `—`
- the session countdown becomes `REOPENS IN 00:57:12`
- the signal line reads `MARKET CLOSED`
- the Δ column in Key Levels dims to `--t2`

**Feed stale** (last tick more than 10s old while the market is open): the `BID` dot turns grey and the price dims to `--t1`. This is how a viewer can tell "live" from "frozen" at a glance.

---

## 7. RAIL — every current feature, arranged as in the reference

1. **NEW YORK CLOSES IN:** large countdown, the close time in UTC, and a thin progress bar showing how far through the session we are.
2. **LIVE SIGNAL · SCANNING:** a gate row `■ TREND  ■ ZONE  □ DISCOUNT  □ R ≥ 1.5`, then one line naming the gate the system is waiting on. This only presents the rejection reasons the producer already logs; it needs no engine change. Filled square = passed, `--acc` outline = the blocking gate, dim outline = not yet evaluated.
3. **INDICATORS:** `Trend M15 · BULLISH · 10:30` and `UT Bot · SELL · 18:00`. Both are persistent state, so they share a section.
4. **KEY LEVELS:** a price ladder sorted by price, highest first, with the current-price row inserted in place and highlighted. Rows above price are above; rows below are below. This is the only section allowed to absorb spare height.
5. **STRUCTURE:** the last three events, with arrows, matching the three on the chart.
6. **WORKLOG:** the last two engine decisions.
7. **SCOREBOARD:** the three tabs, then a 4×2 grid (Win · Loss · Scratch · Hit / Never trig · Cancelled · Void · Expect.), then a footer line `Produced · Triggered · Resolved`. Show the `from 17:00 NY` day boundary in the footer only when TODAY is the active tab.

It must fit at the current window size with nothing clipped.

---

## 8. KEEP — licence requirement

The TradingView attribution mark in the chart's bottom-left is required by the Lightweight Charts licence. Keep it exactly as the library renders it. The reference image leaves it out; the app must not.

---

## 9. ACCEPTANCE

1. **Side-by-side:** an app screenshot next to `oracle-reference.png` at the same window size. List every difference and justify it.
2. The chart plot area contains **no bordered boxes** except the latest-signal chip and live-call tags. Count them with a script rather than by eye.
3. Every chart label has the halo and no background rectangle.
4. Every level line starts at its origin bar (prior-period levels excepted) and ends at the axis with a tag.
5. At most three structure events on the chart, and every one has ▲ or ▼.
6. `grep` finds no `toFixed` or `toLocaleString` outside `fmt`, and no user-facing string literal outside `copy.ts`.
7. The word "points" appears nowhere on the broadcast surface. Spread and distances use the same unit.
8. The pass-2 overlap and clipping scripts are rerun and pass, including the `EXPECTANCY` row and the top axis label.
9. A market-closed screenshot contains no `00:00` anywhere.
10. **Feature parity:** list every element from the previous build and tick each one off: status + handle, settings, session ribbon + next event, symbol, M1–W1, bid/ask/spread/change, scanning line, four clocks including candle close, structure, pools, zones, protected swing, UT signals, current price, watermark, @TradeFix mark, session countdown, trend, live signal, UT Bot state, key levels, structure list, worklog, scoreboard with three tabs and all counts, watching strip, live joins, disclaimer, TradingView attribution.
11. Window size, aspect ratio and scaling are unchanged; diff the window bounds before and after.
12. `engine/` is untouched. The pool-range fix goes in the formatter.
13. The `EQL above price` question from §2 is answered.
