"""Bounded descending MT5 requests nudge the terminal's lazy history download."""

import time
from datetime import UTC, datetime
from typing import Any


def warm_history(api: Any, symbol: str, tf: str, required: int, now_broker_ms: int) -> None:
    if not callable(getattr(api, "copy_rates_from", None)):
        return
    cursor = now_broker_ms
    remaining = required or 100000
    deadline = time.monotonic() + 2
    for _ in range(64):
        if remaining <= 0 or time.monotonic() >= deadline:
            break
        rows = api.copy_rates_from(
            symbol,
            getattr(api, f"TIMEFRAME_{tf}"),
            datetime.fromtimestamp(cursor / 1000, UTC),
            min(5000, remaining),
        )
        if rows is None or not len(rows):
            break
        oldest = int(rows[0]["time"]) * 1000
        if oldest >= cursor:
            break
        remaining -= len(rows)
        cursor = oldest - 1
