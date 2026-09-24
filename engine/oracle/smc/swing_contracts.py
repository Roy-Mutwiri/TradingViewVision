"""Frozen, provenance-bearing outputs of the swing primitive (not detectors)."""

from typing import Annotated, ClassVar, Literal

from pydantic import Field

from oracle.models import Contract, Identified, Millis, NonNegative, Price, Text, Timeframe


class Pivot(Identified):
    identity_fields: ClassVar[tuple[str, ...]] = ("symbol", "tf", "idx", "t_ms", "price", "side")
    symbol: Literal["XAUUSD"] = "XAUUSD"
    tf: Timeframe
    idx: Annotated[int, Field(ge=0)]
    t_ms: Millis
    price: Price
    side: Literal["HIGH", "LOW"]
    kind: Literal["HH", "HL", "LH", "LL"] | None
    confirmed: bool
    confirmed_at_idx: Annotated[int, Field(ge=0)] | None
    confirmed_at_ms: Millis | None
    atr: NonNegative | None
    leg_atr: NonNegative | None
    significant: bool
    opposite_pivot_id: Text | None
    gap_adjacent: bool
    source_bars: tuple[int, ...]
    source_object_ids: tuple[Text, ...]


class EqualPivotPair(Identified):
    identity_fields: ClassVar[tuple[str, ...]] = ("kind", "pivot_ids")
    kind: Literal["EQH", "EQL"]
    price_mean: Price
    pivot_ids: Annotated[tuple[Text, ...], Field(min_length=2)]
    bar_indices: Annotated[tuple[int, ...], Field(min_length=2)]
    count: Annotated[int, Field(ge=2)]
    tolerance: NonNegative
    source_object_ids: tuple[Text, ...]


class SwingSnapshot(Contract):
    schema_version: Literal[1] = 1
    at_idx: int
    internal: tuple[Pivot, ...] = ()
    major: tuple[Pivot, ...] = ()
    provisional: tuple[Pivot, ...] = ()
    equal_pairs: tuple[EqualPivotPair, ...] = ()
    atr: tuple[float | None, ...] = ()

    @property
    def structure_inputs(self) -> tuple[Pivot, ...]:
        """Only confirmed pivots can be supplied to the next primitive."""
        return self.internal

    @property
    def call_inputs(self) -> tuple[Pivot, ...]:
        return tuple(p for p in self.major if p.confirmed and p.significant and p.kind is not None)
