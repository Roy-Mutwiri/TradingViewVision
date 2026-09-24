from datetime import UTC, datetime

from oracle.data.backfill import backfill_step
from oracle.data.broker_clock import BrokerClock, OffsetSpan
from oracle.data.candle_store import CandleStore
from oracle.data.mt5_gateway import Mt5Gateway


class Terminal:
    TIMEFRAME_M1 = 1

    def __init__(self):
        self.cursors = []

    def copy_rates_from(self, symbol, tf, cursor, count):
        self.cursors.append(cursor)
        last = int(cursor.timestamp()) // 60 * 60
        return [
            {
                "time": last - (9 - i) * 60,
                "open": 4300,
                "high": 4301,
                "low": 4299,
                "close": 4300,
                "tick_volume": 100,
            }
            for i in range(10)
        ]

    def shutdown(self):
        pass


def test_backfill_resumes_earliest_cursor_after_reopening_store(tmp_path):
    terminal = Terminal()
    api = Mt5Gateway(terminal)
    clock = BrokerClock(
        broker="exness",
        version=1,
        spans=(
            OffsetSpan(from_broker_ms=None, to_broker_ms=None, offset_s=0, confidence="ASSUMED"),
        ),
    )
    path = str(tmp_path / "candles.duckdb")
    now = int(datetime(2026, 9, 17, 12, tzinfo=UTC).timestamp()) * 1000
    store = CandleStore(path, "exness")
    assert backfill_step(api, store, clock, "XAUUSDz", "M1", now, 2) == 10
    earliest = store.earliest_fetched("XAUUSDz", "M1")
    assert earliest == now - 9 * 60000
    store.close()
    store = CandleStore(path, "exness")
    assert backfill_step(api, store, clock, "XAUUSDz", "M1", now, 2) == 10
    assert round(terminal.cursors[-1].timestamp() * 1000) == earliest - 1
    assert len(store.raw_history("M1")) == 20
    assert store.earliest_fetched("XAUUSDz", "M1") < earliest
    store.close()
    api.close()
