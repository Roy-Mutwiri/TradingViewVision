from __future__ import annotations

import hashlib
import json
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Millis = Annotated[int, Field(ge=0, strict=True)]
Price = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Timeframe = Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
Direction = Literal["BULLISH", "BEARISH", "NEUTRAL"]
ZoneState = Literal["FRESH", "TOUCHED", "MITIGATED", "BREAKER", "INVALID"]
Language = Literal["en", "sw", "es", "fr", "ar", "hi", "pt"]


TF_MS: dict[str, int | None] = {
    "M1": 60000,
    "M5": 300000,
    "M15": 900000,
    "M30": 1800000,
    "H1": 3600000,
    "H4": 14400000,
    "D1": 86400000,
    "W1": 604800000,
    "MN1": None,
}


def timeframe_ms(tf: Timeframe) -> int:
    value = TF_MS[tf]
    if value is None:
        raise ValueError("MN1 is a calendar unit")
    return value


def content_hash(value: object, digits: int = 2) -> str:
    def normalized(item: object) -> object:
        if isinstance(item, float):
            return round(item, digits)
        if isinstance(item, dict):
            return {k: normalized(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalized(v) for v in item]
        return item

    return hashlib.blake2b(
        json.dumps(
            normalized(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode(),
        digest_size=8,
    ).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, populate_by_name=True
    )

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


class Identified(Contract):
    id: str = ""
    object_hash: str = ""
    digits: Literal[2, 3] = Field(default=2)
    identity_fields: ClassVar[tuple[str, ...]] = ()
    mutable_fields: ClassVar[set[str]] = {
        "state",
        "fill_pct",
        "score",
        "reason",
        "text_args",
        "confirmed",
        "reclaimed",
        "confidence",
        "ttl_ms",
        "priority",
        "z",
        "style",
        "anim",
        "lang_variants",
    }

    @model_validator(mode="after")
    def identify(self) -> Self:
        payload = self.model_dump(
            mode="json", by_alias=True, exclude={"id", "object_hash", "digits"}
        )
        identity = (
            {k: v for k, v in payload.items() if k in self.identity_fields}
            if self.identity_fields
            else {k: v for k, v in payload.items() if k not in self.mutable_fields}
        )
        digest = content_hash(identity, self.digits)
        render = content_hash({"id": digest, **payload}, self.digits)
        if self.id and self.id != digest:
            raise ValueError("id does not match identity")
        if self.object_hash and self.object_hash != render:
            raise ValueError("object_hash does not match render content")
        object.__setattr__(self, "id", digest)
        object.__setattr__(self, "object_hash", render)
        return self

    def transition(self, **changes: object) -> Self:
        return type(self).model_validate(
            self.model_dump() | changes | {"object_hash": "", "digits": self.digits}
        )


class Bar(Identified):
    clock_confidence: Literal["MEASURED", "DERIVED", "ASSUMED"] = "ASSUMED"
    identity_fields: ClassVar[tuple[str, ...]] = ("symbol", "tf", "t_open_ms", "o", "h", "l", "c")
    symbol: Literal["XAUUSD"] = "XAUUSD"
    tf: Timeframe
    t_open_ms: Millis
    o: Price
    h: Price
    l: Price  # noqa: E741
    c: Price
    tick_volume: NonNegative
    source: Literal["mt5", "twelve_data", "synthetic"]
    complete: bool

    @model_validator(mode="after")
    def ohlc(self) -> Self:
        if not self.l <= min(self.o, self.c) <= max(self.o, self.c) <= self.h:
            raise ValueError("OHLC envelope is invalid")
        return self


class Quote(Contract):
    symbol: Literal["XAUUSD"]
    bid: Price
    ask: Price
    t_ms: Millis
    source: Text

    @model_validator(mode="after")
    def spread(self) -> Self:
        if self.ask < self.bid:
            raise ValueError("crossed quote")
        return self


class DataQuality(Contract):
    state: Literal["OK", "STALE", "GAPPED", "WIDE_SPREAD", "HALTED", "NO_DATA", "CALENDAR_PENDING"]
    staleness_ms: Millis
    spread_points: NonNegative
    detail: Text  # localization key, never rendered as raw English


class Swing(Identified):
    kind: Literal["HH", "HL", "LH", "LL"]
    idx: Annotated[int, Field(ge=0)]
    t_ms: Millis
    price: Price
    tf: Timeframe


class StructureEvt(Identified):
    kind: Literal["BOS", "CHOCH", "MSS"]
    direction: Direction
    broken_swing_id: Text
    break_bar_idx: Annotated[int, Field(ge=0)]
    t_ms: Millis
    price: Price
    tf: Timeframe
    break_mode: Literal["body", "wick"] = "body"
    confirmed: bool


class Zone(Identified):
    identity_fields: ClassVar[tuple[str, ...]] = (
        "kind",
        "tf",
        "source_bars",
        "price_hi",
        "price_lo",
    )
    kind: Literal["OB", "BREAKER", "FVG", "IFVG", "LIQ_POOL", "OTE", "RANGE", "GAP_FVG"]
    direction: Direction
    tf: Timeframe
    t_start_ms: Millis
    t_end_ms: Millis
    price_hi: Price
    price_lo: Price
    state: ZoneState
    fill_pct: Annotated[float, Field(ge=0, le=100)]
    score: Unit
    reason: Text
    source_bars: Annotated[list[Annotated[int, Field(ge=0)]], Field(min_length=1)]

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.price_hi < self.price_lo or self.t_end_ms < self.t_start_ms:
            raise ValueError("inverted zone bounds")
        return self


class Sweep(Identified):
    level_price: Price
    level_kind: Text
    sweep_bar_idx: Annotated[int, Field(ge=0)]
    t_ms: Millis
    direction: Direction
    reclaimed: bool


class Bias(Contract):
    direction: Direction
    confidence: Unit
    evidence: list[Text]


class BiasStack(Contract):
    per_tf: dict[Timeframe, Bias]
    alignment_score: Unit
    evidence: list[Text]


class SetupGrade(Contract):
    score: Unit
    grade: Literal["A", "B", "C", "D"]
    contributing_factors: Annotated[list[Text], Field(min_length=1)]


class MarketState(Contract):
    as_of_ms: Millis
    symbol: Literal["XAUUSD"]
    price: Price
    swings: list[Swing]
    events: list[StructureEvt]
    zones: list[Zone]
    sweeps: list[Sweep]
    bias: BiasStack
    range_position: Unit
    killzone: str | None
    data_quality: DataQuality
    atr_percentile: Unit
    setup: SetupGrade | None
    tick_size: Price
    active_segment: Text
    state_hash: str = ""

    @model_validator(mode="after")
    def hash_state(self) -> Self:
        digest = content_hash(
            {
                "objects": sorted(
                    (obj.id, obj.object_hash)
                    for obj in [*self.swings, *self.events, *self.zones, *self.sweeps]
                ),
                "price_bucket": round(self.price / self.tick_size),
                "quality": self.data_quality.state,
                "segment": self.active_segment,
            }
        )
        if self.state_hash and self.state_hash != digest:
            raise ValueError("state_hash does not match content")
        object.__setattr__(self, "state_hash", digest)
        return self


class IntelItem(Contract):
    source: Text
    t_ms: Millis
    kind: Text
    headline: Text
    impact: Unit
    payload: dict[str, JsonValue]


class IntelSnapshot(Contract):
    as_of_ms: Millis
    risk_regime: Literal["RISK_ON", "RISK_OFF", "MIXED", "EVENT_PENDING"]
    minutes_to_next_high_impact: NonNegative | None
    next_event: IntelItem | None
    correlates: dict[str, float]
    top_facts: Annotated[list[Text], Field(max_length=3)]
    intel_confidence: Unit


class Waypoint(Contract):
    price: Price
    kind: Literal["ZONE_TAP", "REACTION", "TARGET"]
    note: Text


class Scenario(Identified):
    rank: Literal["PRIMARY", "ALTERNATE", "INVALIDATION"]
    direction: Direction
    waypoints: Annotated[list[Waypoint], Field(min_length=1)]
    invalidation_price: Price
    probability: Unit | None
    prob_sample_n: Annotated[int, Field(ge=0)]
    expected_move_atr: NonNegative
    valid_until_ms: Millis
    reason_chain: Annotated[list[Text], Field(min_length=1)]

    @model_validator(mode="after")
    def sample(self) -> Self:
        if self.probability is not None and self.prob_sample_n == 0:
            raise ValueError("probability requires a sample size")
        return self


class Style(Contract):
    token: Text


class Point(Contract):
    t_ms: Millis
    price: Price


class Animation(Contract):
    in_: Text = Field(alias="in_")
    loop: str | None


class DrawObject(Identified):
    layer: Literal["L2", "L3"]
    shape: Literal["ZONE", "LINE", "RAY", "LABEL", "ARROW", "FIB", "PATH", "LADDER", "GLYPH"]
    points: Annotated[list[Point], Field(min_length=1)]
    style: Style
    text_key: Text
    text_args: dict[str, JsonValue]
    state: ZoneState
    ttl_ms: Millis
    priority: Annotated[int, Field(ge=0)]
    z: int
    anim: Animation
    object_hash: str = ""
    reason: Text
    # Required by section 0 even though omitted from the section 6 sketch.
    source_bars: Annotated[list[Annotated[int, Field(ge=0)]], Field(min_length=1)]
    confidence: Unit


class UTBotDrawObject(DrawObject):
    identity_fields: ClassVar[tuple[str, ...]] = (
        "symbol",
        "tf",
        "t_open_ms",
        "indicator",
        "direction",
    )
    symbol: Literal["XAUUSD"] = "XAUUSD"
    tf: Timeframe
    t_open_ms: Millis
    indicator: Literal["utbot"] = "utbot"
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    warmup: bool = False
    confirmed: bool = True


class DrawPlan(Contract):
    as_of_ms: Millis
    add: list[DrawObject]
    update: list[DrawObject]
    remove: list[Text]

    @model_validator(mode="after")
    def unique_operations(self) -> Self:
        ids = [obj.id for obj in self.add + self.update] + self.remove
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate or conflicting draw operations")
        return self


class CameraTarget(Contract):
    object_id: str | None = None
    from_ms: Millis | None = None
    to_ms: Millis | None = None
    price_lo: Price | None = None
    price_hi: Price | None = None
    tf: Timeframe | None = None

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.from_ms is not None and self.to_ms is not None and self.from_ms > self.to_ms:
            raise ValueError("inverted camera time range")
        if (
            self.price_lo is not None
            and self.price_hi is not None
            and self.price_lo > self.price_hi
        ):
            raise ValueError("inverted camera price range")
        return self


class CameraMove(Contract):
    kind: Literal["PAN", "ZOOM_TO_ZONE", "FRAME_RANGE", "TF_MORPH"]
    target: CameraTarget
    duration_ms: Millis
    easing: Literal["linear", "ease_in_out", "ease_out"]


class HighlightCue(Contract):
    object_id: Text
    at_ms: Millis
    kind: Literal["PULSE", "FLASH", "TRACE"]


class PresentationBeat(Contract):
    segment_id: Text
    draw_plan: DrawPlan
    camera: CameraMove | None
    cues: list[HighlightCue]


class DataGapHealed(Contract):
    symbol: Literal["XAUUSD"]
    from_ms: Millis
    to_ms: Millis
    bars_recovered: Annotated[int, Field(ge=0)]


class BarCorrection(Contract):
    previous: Bar
    corrected: Bar
    deviation: NonNegative


class WireEvent(Contract):
    version: Literal[1] = 1
    sequence: Annotated[int, Field(ge=0)]
    t_ms: Millis
    payload: (
        Bar
        | BarCorrection
        | Quote
        | DataQuality
        | DataGapHealed
        | MarketState
        | IntelSnapshot
        | PresentationBeat
    )
