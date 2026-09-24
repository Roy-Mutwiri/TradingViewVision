# Chart label minimalism

UT Bot renders only Buy/Sell chips, including provisional signals. Its original
evidence and parameter values remain in DrawObject records and are displayed
only under **UT Bot signal evidence** in the diagnostics drawer. Historical
signals never gain explanatory text. The optional eight-second numeric signal
text is omitted under the stronger chips-only ruling.

All chart annotations share one placement pass. Calls outrank zones, levels,
structure and indicator signals. Newer objects win within a priority. The
ten-text-line budget includes every line in a call strip. Bodies have a
two-pixel clearance and labels a three-pixel clearance. Labels start outside
their source candle's wick; two vertical nudges are attempted before they
collapse to a six-pixel triangle. Labels are clipped to the plot, never placed
on the axes. Axis ticks are outside this annotation budget.

Filled chips have dark 12px semibold monospace text; call strips use 13px and
at most three compact lines. The strip's display projection retains market
tags, prices and times, removes parameter values, and does not edit the stored
reason chain. Its local expiry repaint works even without another tick and
cannot extend past twenty seconds on repeated frames. The associated call
chip remains when a strip expires.

Axis prices use whole dollars and thousands separators; chip prices use two
decimals. The header keeps the instrument's full precision. Monospace chart
fonts and tabular numeral styling prevent digit-width jitter.

The next-close card contains a title and countdown. Candle reference panels
are removed; OHLC remains in the crosshair and live-candle drawer. The unbuilt
bias engine has one muted line. The scoreboard and permanent disclaimer remain.
Desktop geometry, resolution and scaling are unchanged.

Verification: `npm run test:labels` checks priorities, the cap, collision and
body clearance, two nudges, markers, and formatting. Playwright captures a
dense signal day, checks rendered text and chip overlaps, and confirms signal
evidence appears only in the drawer. Reviewed screenshots cover both themes.
