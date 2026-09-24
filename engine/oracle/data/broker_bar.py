"""Raw and normalized bar provenance; deliberately absent from wire models."""

from typing import Literal, Self

from pydantic import Field, model_validator

from oracle.data.broker_clock import BrokerClock
from oracle.models import Bar, Contract, Millis, NonNegative, Price, Timeframe


class RawBrokerBar(Contract):
    tf: Timeframe
    t_broker_ms: Millis
    o: Price
    h: Price
    l: Price  # noqa: E741
    c: Price
    tick_volume: NonNegative
    digits: Literal[2, 3]
    complete: bool

    @model_validator(mode="after")
    def envelope(self) -> Self:
        if not self.l <= min(self.o, self.c) <= max(self.o, self.c) <= self.h:
            raise ValueError("OHLC envelope is invalid")
        return self

    def normalize(self, clock: BrokerClock) -> "BrokerBar":
        bar = Bar.model_validate(
            self.model_dump(exclude={"t_broker_ms"})
            | {
                "t_open_ms": clock.utc_ms(self.t_broker_ms),
                "source": "mt5",
                "clock_confidence": clock.confidence_at(self.t_broker_ms),
            }
        )
        return BrokerBar(raw=self, t_open_ms=bar.t_open_ms, clock_version=clock.version, bar=bar)


class BrokerBar(Contract):
    raw: RawBrokerBar
    t_open_ms: Millis
    clock_version: int = Field(ge=1, strict=True)
    bar: Bar

    @property
    def t_broker_ms(self) -> int:
        return self.raw.t_broker_ms

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.bar.source != "mt5" or self.bar.t_open_ms != self.t_open_ms:
            raise ValueError("Broker provenance does not match normalized bar")
        if self.bar.model_dump(
            exclude={"id", "object_hash", "t_open_ms", "symbol", "source", "clock_confidence"}
        ) != self.raw.model_dump(exclude={"t_broker_ms"}):
            raise ValueError("Broker provenance does not match raw prices")
        return self
