"""Explicit input sources: buckets and OHLC conventions, no clock reads."""

from collections.abc import Sequence
from typing import Literal

from oracle.candidates.contracts import EvalPoint
from oracle.models import Bar, Contract, timeframe_ms


class CoarseSpan(Contract):
    state: str = "SYNTHETIC_COARSE"
    start_ms: int
    end_ms: int
    reason: str = "Missing constituent M1 coverage"


def traversal(bar: Bar) -> tuple[float, float, float, float]:
    return (bar.o, bar.l, bar.h, bar.c) if bar.c >= bar.o else (bar.o, bar.h, bar.l, bar.c)


def replay_points(parents: Sequence[Bar], minutes: Sequence[Bar], *, offset_s: int = 0,
                  coarse_only: bool = False) -> tuple[list[EvalPoint], list[CoarseSpan]]:
    by_time = {bar.t_open_ms: bar for bar in minutes if bar.complete and bar.tf == "M1"}
    points: list[EvalPoint] = []
    spans: list[CoarseSpan] = []
    for index, parent in enumerate(parents):
        if not parent.complete:
            raise ValueError("replay parent bars must be confirmed")
        duration = timeframe_ms(parent.tf)
        expected = range(parent.t_open_ms, parent.t_open_ms+duration, 60000)
        constituent = [by_time[t] for t in expected if t in by_time]
        coarse = coarse_only or len(constituent) != duration//60000
        if coarse:
            missing = [t for t in expected if t not in by_time]
            spans.append(CoarseSpan(start_ms=min(missing) if missing else parent.t_open_ms,
                                    end_ms=max(missing)+60000 if missing else parent.t_open_ms+duration))
            constituent = [parent]
        for mi, minute in enumerate(constituent):
            unit_duration = duration if coarse else 60000
            for step, price in enumerate(traversal(minute)):
                final = mi == len(constituent)-1 and step == 3
                phase: Literal["OPEN", "INTRA", "CLOSE"] = "CLOSE" if final else "OPEN" if mi == 0 and step == 0 else "INTRA"
                at = minute.t_open_ms + (unit_duration if final else step*unit_duration//4)
                points.append(EvalPoint(seq=len(points), t_broker_ms=at+offset_s*1000,
                                        price=parent.c if final else price, bar_index=index,
                                        bar_phase=phase, source="BAR_COARSE" if coarse else "M1_SYNTH",
                                        fidelity="BAR" if coarse else "M1"))
    return points, spans


class LiveBuckets:
    def __init__(self, bucket_ms: int = 250) -> None:
        if bucket_ms <= 0:
            raise ValueError("bucket size must be positive")
        self.bucket_ms = bucket_ms
        self.pending: tuple[int, float, int, int] | None = None
        self.seq = 0
        self.seen_bars: set[int] = set()
        self.closed_bars: set[int] = set()

    def _flush(self) -> EvalPoint | None:
        if self.pending is None:
            return None
        at, price, index, _ = self.pending
        phase: Literal["OPEN", "INTRA", "CLOSE"] = "INTRA" if index in self.seen_bars else "OPEN"
        self.seen_bars.add(index)
        result = EvalPoint(seq=self.seq, t_broker_ms=at, price=price, bar_index=index,
                           bar_phase=phase, source="LIVE_TICK", fidelity="TICK")
        self.seq += 1
        self.pending = None
        return result

    def ingest(self, t_broker_ms: int, price: float, bar_index: int) -> list[EvalPoint]:
        if bar_index in self.closed_bars:
            raise ValueError("late tick for a closed bar")
        bucket = t_broker_ms//self.bucket_ms
        result: list[EvalPoint] = []
        if self.pending is not None:
            if t_broker_ms < self.pending[0]:
                raise ValueError("ticks must be ordered")
            if bucket != self.pending[3] or bar_index != self.pending[2]:
                point = self._flush()
                if point is not None:
                    result.append(point)
        self.pending = (t_broker_ms, price, bar_index, bucket)
        return result

    def close(self, t_broker_ms: int, price: float, bar_index: int) -> list[EvalPoint]:
        if bar_index in self.closed_bars:
            raise ValueError("duplicate CLOSE")
        if self.pending is not None and self.pending[2] != bar_index:
            raise ValueError("CLOSE must precede ticks in the next bar")
        result: list[EvalPoint] = []
        pending = self._flush()
        if pending is not None:
            result.append(pending)
        result.append(EvalPoint(seq=self.seq, t_broker_ms=t_broker_ms, price=price,
                                bar_index=bar_index, bar_phase="CLOSE",
                                source="LIVE_TICK", fidelity="TICK"))
        self.seq += 1
        self.closed_bars.add(bar_index)
        return result
