"""Chart-only UTC contracts. Debug provenance travels on a separate channel."""

from typing import Any, Literal

from oracle.candidates.contracts import Decision
from oracle.models import (
    Bar,
    Contract,
    DataQuality,
    DrawObject,
    Millis,
    Quote,
    Timeframe,
    UTBotDrawObject,
)
from oracle.smc.liquidity_contracts import Pool
from oracle.smc.structure import StructureState
from oracle.smc.worklog import WorkDecision
from oracle.transport.errors import EngineFault


class BarsSnapshot(Contract):
    symbol: Literal["XAUUSD"] = "XAUUSD"
    tf: Timeframe
    bars: list[Bar]
    clockVersion: int


class BarUpdate(Contract):
    symbol: Literal["XAUUSD"] = "XAUUSD"
    tf: Timeframe
    bar: Bar


class BarCorrection(BarUpdate):
    pass


class SessionClosure(Contract):
    start_ms: Millis
    end_ms: Millis
    recurring: bool


class BarColor(Contract):
    t_ms: Millis
    token: str


class TickQuote(Contract):
    quote: Quote
    received_ms: Millis
    now_ms: Millis
    digits: Literal[2, 3]
    spread_points: float

    def wire(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        for field in ("bid", "ask"):
            payload["quote"][field] = round(payload["quote"][field], self.digits)
        return payload


class ChartFrame(Contract):
    chart_density: Literal["clean", "analyst", "notebook"] = "clean"
    thesis: dict[str, Any] = {}
    book: dict[str, Any] = {}
    liquidity_pools: list[Pool] = []
    liquidity_weekly_open: float | None = None
    structure_state: StructureState | None = None
    candidate_decisions: list[Decision] = []
    candidate_worklog: list[Decision] = []
    candidate_status: dict[str, Any] = {}
    worklog: list[WorkDecision] = []
    kind: Literal["snapshot", "update", "correction", "status", "clock_refined"]
    resolved_symbol: str = ""
    refinement_pending: str = "Clock transition derivation pending: 30 days of M1 required"
    quote: Quote | None = None
    objects: list[DrawObject | UTBotDrawObject] = []
    indicator_enabled: bool = False
    switch_ms: float = 0
    bar_colors: list[BarColor] = []
    language: str = "en"
    snapshot: BarsSnapshot | None = None
    update: BarUpdate | None = None
    quality: DataQuality
    now_ms: Millis
    next_close_ms: Millis | None = None
    bar_duration_ms: Millis
    closures: list[SessionClosure] = []
    calendar_detail: str = "Calendar unavailable"

    def wire(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        bars = payload["snapshot"]["bars"] if payload["snapshot"] else []
        if payload["update"]:
            bars = bars + [payload["update"]["bar"]]
        for bar in bars:
            for field in ("o", "h", "l", "c"):
                bar[field] = round(bar[field], bar["digits"])
        return payload


class DebugBar(Contract):
    clock_confidence: str = "ASSUMED"
    t_open_ms: Millis
    t_broker_ms: Millis
    offset_s: int
    clock_version: int


class ChartDebug(Contract):
    error: EngineFault | None = None
    resolved_symbol: str
    bars: list[DebugBar]
    corrections: int
    checked: int
    last_tick_ms: Millis
    spread_points: float
    detail: str
    switch_ms: float = 0
    gateway: dict[str, Any] = {}
    missing_ranges: list[dict[str, int]] = []
    indicator: dict[str, Any] = {}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    from pydantic import TypeAdapter

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    schema = TypeAdapter(ChartFrame | ChartDebug | BarCorrection | TickQuote).json_schema(
        mode="serialization"
    )
    args.output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")

