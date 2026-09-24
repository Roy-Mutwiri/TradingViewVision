# Phase 5 checkpoint: section 0

Studio is permanently silent. The Windows voice implementation, speech test,
Python output package, presentation speech contract and private status IPC have
been deleted. Capture explicitly uses `-an`; the existing retained MP4 was
checked and already contains only a video stream. No sound library is declared
in the app or engine dependency manifests.

The requested `narration` config name remains only for on-chart explanations.
`audio` is constrained to false, and a configuration attempting to enable it
fails validation. `on_chart_reasons` remains true and `reason_strip_seconds`
defaults to 20.

Call reason chains are immutable tuples. Empty legacy chains preserve existing
ledger IDs; new chains participate in call identity. A reason strip projects the
first three stored entries verbatim into an L3 DrawObject at the entry midpoint,
and expires exactly 20 seconds after creation. Different calls at the same
level receive different drawing IDs. The existing canvas renderer displays
stored object reasons on opaque filled chips, with neutral ink. It generates
no explanatory prose.

Window geometry, aspect ratio, resolution and display scaling are unchanged.
Section 1, the deterministic setup producer, has not started. The ten-minute
live proof depends on that producer and the later tick/display integration;
it is not claimed by this checkpoint.
