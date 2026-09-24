"""Instrument economics loaded exclusively at the feed boundary."""

from typing import Any, Literal

from oracle.models import Contract, Price


class Instrument(Contract):
    digits: Literal[2, 3]
    point: Price
    tick_size: Price
    contract_size: Price

    @classmethod
    def from_mt5(cls, info: Any) -> "Instrument":
        if info is None or info.digits not in (2, 3) or info.trade_contract_size != 100:
            raise ValueError("HALTED: unexpected instrument economics")
        return cls(
            digits=info.digits,
            point=info.point,
            tick_size=info.trade_tick_size,
            contract_size=info.trade_contract_size,
        )

    @property
    def usd_per_point_per_lot(self) -> float:
        return self.contract_size * self.point

    def equal(self, a: float, b: float) -> bool:
        return abs(a - b) <= self.tick_size / 2

    def contains(self, lo: float, hi: float, price: float) -> bool:
        return lo - self.tick_size / 2 <= price <= hi + self.tick_size / 2
