"""Resumable small bulk steps, with a private DuckDB connection off the IPC path."""

from datetime import UTC, datetime
from typing import Literal

from oracle.data.broker_bar import RawBrokerBar
from oracle.data.broker_clock import BrokerClock
from oracle.data.candle_store import CandleStore
from oracle.data.mt5_gateway import Mt5Gateway
from oracle.models import Timeframe


def backfill_step(
    api: Mt5Gateway,
    store: CandleStore,
    clock: BrokerClock,
    symbol: str,
    tf: Timeframe,
    now_broker_ms: int,
    digits: Literal[2, 3],
) -> int:
    cursor = store.earliest_fetched(symbol, tf)
    with api.priority(api.PRIORITY_BULK):
        rows = api.copy_rates_from(
            symbol,
            getattr(api, f"TIMEFRAME_{tf}"),
            datetime.fromtimestamp(
                (cursor - 1 if cursor is not None else now_broker_ms) / 1000, UTC
            ),
            1000,
        )
    raw: list[RawBrokerBar] = []
    for row in rows if rows is not None else []:
        raw.append(
            RawBrokerBar(
                tf=tf,
                t_broker_ms=int(row["time"]) * 1000,
                o=float(row["open"]),
                h=float(row["high"]),
                l=float(row["low"]),
                c=float(row["close"]),
                tick_volume=float(row["tick_volume"]),
                digits=digits,
                complete=cursor is not None
                or int(row["time"]) * 1000 < now_broker_ms // 60000 * 60000,
            )
        )
    if raw:
        for i in range(0, len(raw), 250):
            store.put_broker_many([b.normalize(clock) for b in raw[i : i + 250]])
        store.save_cursor(symbol, tf, min(b.t_broker_ms for b in raw))
    return len(raw)
