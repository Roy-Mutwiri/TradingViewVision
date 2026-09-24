"""Build M1 bid bars and reconcile closed minutes against broker rates."""

import logging
from typing import Literal

from oracle.data.candle_store import CandleStore
from oracle.models import Bar, BarCorrection


class TickBuilder:
    def __init__(self, tick_size: float, digits: Literal[2, 3]) -> None:
        self.tick_size, self.digits = tick_size, digits
        self.current: Bar | None = None
        self.checked = 0
        self.corrections = 0

    def ingest(self, t_ms: int, bid: float) -> Bar | None:
        t = t_ms // 60000 * 60000
        previous = self.current
        if previous and t < previous.t_open_ms:
            raise ValueError("Out-of-order tick")
        closed = None
        if previous is None or t != previous.t_open_ms:
            if previous:
                closed = previous.transition(complete=True)
            self.current = Bar(
                tf="M1",
                t_open_ms=t,
                o=bid,
                h=bid,
                l=bid,
                c=bid,
                tick_volume=1,
                source="mt5",
                complete=False,
                digits=self.digits,
            )
        else:
            payload = previous.model_dump(exclude={"id", "object_hash"})
            self.current = Bar.model_validate(
                payload
                | {
                    "h": max(previous.h, bid),
                    "l": min(previous.l, bid),
                    "c": bid,
                    "tick_volume": previous.tick_volume + 1,
                    "digits": self.digits,
                }
            )
        return closed

    def reconcile(self, built: Bar, broker: Bar, store: CandleStore) -> BarCorrection | None:
        if built.t_open_ms != broker.t_open_ms or broker.source != "mt5":
            raise ValueError("Reconciliation requires matching broker minute")
        self.checked += 1
        deviation = max(
            abs(getattr(built, key) - getattr(broker, key)) for key in ("o", "h", "l", "c")
        )
        if deviation > self.tick_size:
            store.put(broker)
            self.corrections += 1
            logging.getLogger(__name__).warning(
                "BarCorrection rate=%s", self.corrections / self.checked
            )
            return BarCorrection(previous=built, corrected=broker, deviation=deviation)
        store.put(built)
        return None
