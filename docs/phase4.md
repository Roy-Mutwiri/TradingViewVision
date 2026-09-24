# Phase 4: broadcast surface and retention

The existing landscape window and display scaling are preserved. Broadcast is
the launch default (`ui.mode` in `config/oracle.yaml`). F9 switches between
broadcast and operator surfaces; backtick opens the operator drawer in either
mode. The DEMO/REAL badge and educational disclaimer remain visible in both.
Broadcast shows symbol identity, bid/ask/spread, session, candle countdown and
colour-only health indicators. Clock/calendar progress, capability warnings,
counts, tick age and latency remain on the operator surface or in its drawer.
Broadcast failures say the chart is paused; operator mode retains the typed
cause, diagnostics and recovery action. Internal stack locations exclude source
text, argument values and arbitrary exception messages.
An operator drawer is deliberately diagnostic: close it before broadcasting.

The engine owns answers, moderated names, analysis results and chart reference
objects. The renderer projects frozen `RetentionFrame` contracts and does not
calculate predictions. The audience decision panel and bottom decision bar have
been removed. Candle closes are facts and never create scoreboard entries.

The scoreboard header remains "THE SCOREBOARD · LOSSES STAY". Only engine-supplied
falsifiable SETUP and STRUCTURE calls enter it through `Director.create_call`.
The M1 resolver owns outcomes and append-only persistence. LAST 20 is the default;
scratch, never-triggered, cancelled and void-data counts remain visible. TODAY
uses the analytical trading day and ALL TIME retains every record. See
[analysis accountability](analysis-calls.md). Audience comments and support cannot
change outcomes. The analysis producer remains a scaffold; no calls are fabricated.

Commands from one handle are limited to one per 20 seconds. Answer cards are held for 13 seconds and
limited to one per 45 seconds. A moderated four-second comment echo appears
immediately even when an answer is queued. Bias cards last eight seconds; an
engine-confirmed zone command lasts six seconds and restores the prior range.
Follower/comment shout-outs and gift thanks have no effect on access or scores.

SMC analysis is not implemented in this scaffold. Bias is explicitly NOT
ASSESSED and no active zone is invented. The default three references are the
verified candle's high, open and low, labelled as candle references. The Director
accepts justified engine bias, levels and a DrawObject zone when that engine is
available. UT Bot remains an indicator outside SMC confluence and spoken calls.

## Local audience input

`retention.gamechanger_events` points to GamechangerTalker's local LiveBridge
JSONL directory. The shipped sibling-workspace path is
`../LetsTalk/data/live_events`. Existing records are skipped on attachment;
new submitted events are read, deduplicated and moderated. Dropped/quiet events
are ignored. Partial lines and log rotation are supported. Handles are plain
isolated text, capped at 18 graphemes for display; full normalized identity is
used for rate limits. Profanity, impersonation, private account fields
and unsafe audience text are rejected before rendering.

The sibling Gamechanger source currently implements operator-relayed chat,
mock input and replay; its live TikTok source raises NotImplementedError.
ORACLE's latency guarantee starts when an event reaches the local bridge log.
This integration does not claim automatic ingestion from TikTok itself.

Commands: !bias, !levels, !score, !zone, and questions containing `?`.
The standalone bridge's current records do not supply viewer counts. When a
normalized event supplies `viewer_count` (directly or in metadata), fresh counts
are sampled every ten seconds. Counts are never inferred from comments.

## Reports and build checks

Timeline files are written under `runtime/retention` by default. From `engine/`:

```powershell
..\.venv312\Scripts\python.exe -m oracle.director.timeline <timeline.jsonl> --output <report.json>
```

The report groups beats by type and computes average viewer delta only where
fresh viewer samples cover both ends. Missing measurements are `null` and marked
unmeasured. `python -m oracle.replay.retention` produces an explicitly synthetic
replay for development; it is not live-audience evidence.

Protocol generation/checking verifies the silent presentation contracts.
Python tests cover engine result recording,
deduplication, retained losses, moderation, ingestion and a full 60-minute
deterministic replay. UI tests cover diagnostics isolation,
names, permanent items, opaque chart labels and direction-only green/red.

## Native capture

From `app/`, with the saved authorized local DEMO profile available:

```powershell
$env:ORACLE_RUN_WINDOWS_LIVE = '1'
node scripts/capture-phase4.mjs
# For the actual one-hour capture, sampled in both modes:
$env:ORACLE_CAPTURE_MINUTES = '60'
node scripts/capture-phase4.mjs
```

This opt-in harness uses real Exness candles and isolated scripted audience
events visibly marked REHEARSAL. It never sends rehearsal comments or gifts to
TikTok or the real Talker feed. Passwords are retrieved through the existing
keychain connection path and never enter the test process. The saved account
uses a master DEMO profile; the capability chip is visible only in operator mode,
as required by the surface split. No order-placement path is added.

The harness preserves native geometry and samples badge, disclaimer, scoreboard,
diagnostic isolation and geometry every second. A full-hour capture switches
surfaces every five minutes. The output includes the capture report, real stream
timeline and retention report, plus a constant 3.5 Mbps silent H.264 encode.
The encoder explicitly omits sound. An odd existing
window height uses 4:4:4 encoding to preserve every original pixel without
resizing or padding. FFmpeg comes from the proof environment's imageio-ffmpeg
package; it is not a runtime product dependency.

Evidence lives in `artifacts/phase4/`. Three-minute evidence uses
`broadcast-proof*`; full-hour evidence uses `hour-soak*`. Read each JSON report's
provenance and duration before treating it as a completed gate. The recorded
retention report will correctly show unmeasured viewer deltas until an actual
viewer-count source is attached.
