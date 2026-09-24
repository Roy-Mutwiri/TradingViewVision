"""Append-only facts projected from completed detector decisions, never commentary."""

from typing import Literal

from oracle.models import Contract, Millis, Text, Timeframe


class WorkDecision(Contract):
    id: Text
    at_ms: Millis
    tf: Timeframe
    object_id: Text
    action: Literal["MARKED", "CE_LOST", "INVERTED", "INVALID", "MERGED", "MERGE_REJECTED", "REINVERSION_ATTEMPT"]
    label: Text
    source_bars: tuple[int, ...]
    source_object_ids: tuple[str, ...]
