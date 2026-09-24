"""Broadcast allow-list: market facts and moderated audience text, never account money."""

from typing import Literal

from pydantic import Field

from oracle.analysis.contracts import CallBoard
from oracle.models import Contract, DrawObject, Millis


class Hook(Contract):
    kind: Literal[
        "CANDLE_CLOSE",
        "LEVEL_APPROACH",
        "EVENT_COUNTDOWN",
        "SETUP_TRIGGER",
        "STREAK",
        "SESSION_OPEN",
    ]
    headline: str
    sub: str
    countdown_ms: int = Field(ge=0)
    ring_pct: float = Field(ge=0, le=1)
    priority: int
    id: str
    ends_ms: Millis
    outcome: str | None = None


class Card(Contract):
    id: str
    kind: Literal["ANSWER", "BIAS", "LEVELS", "SCORE", "ZONE", "THANKS"]
    handle: str
    question: str
    answer: str
    ends_ms: Millis


class Level(Contract):
    label: str
    price: float


class AudienceComment(Contract):
    handle: str
    text: str
    at_ms: Millis
    ends_ms: Millis


class RetentionFrame(Contract):
    now_ms: Millis
    hook: Hook
    card: Card | None = None
    shout: str | None = None
    supporters: list[str] = []
    scoreboard: CallBoard = CallBoard()
    levels: list[Level] = []
    bias: dict[str, str] = {"H4": "NOT ASSESSED", "H1": "NOT ASSESSED", "M15": "NOT ASSESSED"}
    session: str = "Gold / UTC"
    language: str = "en"
    zoom: dict[str, int | float] | None = None
    marks: list[DrawObject] = []
    rehearsal: bool = False
    comment: AudienceComment | None = None


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(RetentionFrame.model_json_schema(mode="serialization"), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
