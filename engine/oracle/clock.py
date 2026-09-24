"""Injected UTC clocks. Replay time never consults wall time."""

import time
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


class ReplayClock:
    def __init__(self, start_ms: int = 0) -> None:
        if start_ms < 0:
            raise ValueError("negative epoch")
        self._now_ms = start_ms

    def now_ms(self) -> int:
        return self._now_ms

    def advance_to(self, t_ms: int) -> None:
        if t_ms < self._now_ms:
            raise ValueError("replay clock cannot go backwards")
        self._now_ms = t_ms
