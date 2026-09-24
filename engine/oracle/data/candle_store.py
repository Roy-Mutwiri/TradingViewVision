"""Broker-keyed persistent bars with authoritative-source precedence."""

import threading
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable

import duckdb
import pandas  # type: ignore[import-untyped] # noqa: F401 -- preload DuckDB's type adapter.

from oracle.data.broker_bar import BrokerBar, RawBrokerBar
from oracle.data.broker_clock import BrokerClock
from oracle.models import Bar, Timeframe


def serialized_write(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def run(self: "CandleStore", *args: Any, **kwargs: Any) -> Any:
        with self._write_lock:
            return method(self, *args, **kwargs)

    return run


class CandleStore:
    def __init__(self, path: str, broker: str) -> None:
        if not broker.strip():
            raise ValueError("canonical broker required")
        self.broker = broker
        self._write_lock = threading.RLock()
        self._bar_cache: OrderedDict[str, Bar] = OrderedDict()
        self.path = path
        self.active_clock_version: int | None = None
        self.db = duckdb.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS bars (broker VARCHAR, tf VARCHAR, t BIGINT, source VARCHAR, payload VARCHAR, PRIMARY KEY(broker, tf, t))"
        )
        self.db.execute("ALTER TABLE bars ADD COLUMN IF NOT EXISTS t_broker_ms BIGINT")
        self.db.execute("ALTER TABLE bars ADD COLUMN IF NOT EXISTS clock_version INTEGER")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS raw_bars (broker VARCHAR, tf VARCHAR, "
            "t_broker_ms BIGINT, payload VARCHAR, PRIMARY KEY(broker, tf, t_broker_ms))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS feed_identity (broker VARCHAR PRIMARY KEY, server VARCHAR)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS backfill_cursor (broker VARCHAR, symbol VARCHAR, tf VARCHAR, earliest BIGINT, PRIMARY KEY(broker,symbol,tf))"
        )

    def earliest_fetched(self, symbol: str, tf: Timeframe) -> int | None:
        row = self.db.execute(
            "SELECT earliest FROM backfill_cursor WHERE broker=? AND symbol=? AND tf=?",
            [self.broker, symbol, tf],
        ).fetchone()
        if row:
            return int(row[0])
        known = self.db.execute(
            "SELECT min(t_broker_ms) FROM raw_bars WHERE broker=? AND tf=?", [self.broker, tf]
        ).fetchone()
        return int(known[0]) if known and known[0] is not None else None

    def save_cursor(self, symbol: str, tf: Timeframe, earliest: int) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO backfill_cursor VALUES (?,?,?,?)",
            [self.broker, symbol, tf, earliest],
        )

    def latest(self, tf: Timeframe, count: int) -> list[Bar]:
        rows = self.db.execute(
            "SELECT payload,clock_version FROM bars WHERE broker=? AND tf=? ORDER BY t DESC LIMIT ?",
            [self.broker, tf, count],
        ).fetchall()
        result = []
        for payload, version in reversed(rows):
            if (
                self.active_clock_version is not None
                and version is not None
                and version != self.active_clock_version
            ):
                raise ValueError("clock changed, reconstruct UTC projection before reading bars")
            bar = self._bar_cache.get(payload)
            if bar is None:
                bar = Bar.model_validate_json(payload)
                self._bar_cache[payload] = bar
                if len(self._bar_cache) > 20000:
                    self._bar_cache.popitem(last=False)
            result.append(bar)
        return result

    def fork(self) -> "CandleStore":
        """An independent connection for one background owner, including in-memory tests."""
        connection = CandleStore.__new__(CandleStore)
        connection.broker, connection.path = self.broker, self.path
        connection._write_lock = self._write_lock
        connection._bar_cache = OrderedDict()
        connection.active_clock_version = self.active_clock_version
        connection.db = self.db.cursor()
        return connection

    def bind_server(self, server: str) -> None:
        previous = self.db.execute(
            "SELECT server FROM feed_identity WHERE broker=?", [self.broker]
        ).fetchone()
        if previous and previous[0] != server:
            raise ValueError(
                "HALTED: canonical broker server changed; use a separate history store"
            )
        self.db.execute("INSERT OR IGNORE INTO feed_identity VALUES (?, ?)", [self.broker, server])

    @serialized_write
    def archive_raw(self, raw: RawBrokerBar) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO raw_bars VALUES (?, ?, ?, ?)",
            [self.broker, raw.tf, raw.t_broker_ms, raw.canonical_json()],
        )

    @serialized_write
    def archive_raw_many(self, bars: list[RawBrokerBar]) -> None:
        if not bars:
            return
        self.db.execute(
            "INSERT OR REPLACE INTO raw_bars SELECT unnest(?), unnest(?), unnest(?), unnest(?)",
            [
                [self.broker] * len(bars),
                [b.tf for b in bars],
                [b.t_broker_ms for b in bars],
                [b.canonical_json() for b in bars],
            ],
        )

    @serialized_write
    def put_broker_many(self, records: list[BrokerBar]) -> None:
        if not records:
            return
        self.archive_raw_many([r.raw for r in records])
        keys = {(r.bar.tf, r.t_open_ms) for r in records}
        if len(keys) != len(records):
            raise ValueError("HALTED: distinct broker bars collapse to the same UTC timestamp")
        self.db.execute("BEGIN TRANSACTION")
        try:
            self.db.execute(
                "CREATE TEMP TABLE incoming_chart AS SELECT unnest(?) AS broker, unnest(?) AS tf, unnest(?) AS t, unnest(?) AS source, unnest(?) AS payload, unnest(?) AS t_broker_ms, unnest(?) AS clock_version",
                [
                    [self.broker] * len(records),
                    [r.bar.tf for r in records],
                    [r.t_open_ms for r in records],
                    ["mt5"] * len(records),
                    [r.bar.canonical_json() for r in records],
                    [r.t_broker_ms for r in records],
                    [r.clock_version for r in records],
                ],
            )
            collision = self.db.execute(
                "SELECT count(*) FROM bars b JOIN incoming_chart i ON b.broker=i.broker AND b.tf=i.tf AND b.t=i.t WHERE b.source='mt5' AND b.t_broker_ms IS NOT NULL AND b.t_broker_ms<>i.t_broker_ms"
            ).fetchone()
            if collision and collision[0]:
                raise ValueError("HALTED: distinct broker bars collapse to the same UTC timestamp")
            self.db.execute(
                "DELETE FROM bars USING incoming_chart i WHERE bars.broker=i.broker AND bars.tf=i.tf AND bars.t_broker_ms=i.t_broker_ms"
            )
            self.db.execute("INSERT OR REPLACE INTO bars SELECT * FROM incoming_chart")
            self.db.execute("DROP TABLE incoming_chart")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def bind_account(self, server: str, login: int) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS account_identity (broker VARCHAR PRIMARY KEY, server VARCHAR, login BIGINT)"
        )
        previous = self.db.execute(
            "SELECT server, login FROM account_identity WHERE broker=?", [self.broker]
        ).fetchone()
        if previous and previous != (server, login):
            raise ValueError("Account switch requires an isolated history store and engine restart")
        self.db.execute(
            "INSERT OR IGNORE INTO account_identity VALUES (?, ?, ?)", [self.broker, server, login]
        )

    def expect_clock(self, clock: BrokerClock) -> None:
        if clock.broker != self.broker:
            raise ValueError("Clock/store broker mismatch")
        self.active_clock_version = clock.version

    def raw_history(self, tf: Timeframe) -> list[RawBrokerBar]:
        return [
            RawBrokerBar.model_validate_json(row[0])
            for row in self.db.execute(
                "SELECT payload FROM raw_bars WHERE broker=? AND tf=? ORDER BY t_broker_ms",
                [self.broker, tf],
            ).fetchall()
        ]

    @serialized_write
    def put_broker(self, record: BrokerBar) -> None:
        # Preserve the broker's untouched epoch even if projection validation fails.
        self.archive_raw(record.raw)
        self.db.execute("BEGIN TRANSACTION")
        try:
            self._put_projection(record)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _put_projection(self, record: BrokerBar) -> None:
        collision = self.db.execute(
            "SELECT t_broker_ms FROM bars WHERE broker=? AND tf=? AND t=? AND source='mt5'",
            [self.broker, record.bar.tf, record.t_open_ms],
        ).fetchone()
        if collision and collision[0] is not None and collision[0] != record.t_broker_ms:
            raise ValueError("HALTED: distinct broker bars collapse to the same UTC timestamp")
        self.db.execute(
            "DELETE FROM bars WHERE broker=? AND tf=? AND t_broker_ms=?",
            [self.broker, record.bar.tf, record.t_broker_ms],
        )
        self.db.execute(
            "INSERT OR REPLACE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                self.broker,
                record.bar.tf,
                record.t_open_ms,
                "mt5",
                record.bar.canonical_json(),
                record.t_broker_ms,
                record.clock_version,
            ],
        )

    @serialized_write
    def reproject(self, clock: BrokerClock) -> int:
        if clock.broker != self.broker:
            raise ValueError("Clock/store broker mismatch")
        rows = self.db.execute(
            "SELECT payload FROM raw_bars WHERE broker=? ORDER BY tf, t_broker_ms", [self.broker]
        ).fetchall()
        records = [RawBrokerBar.model_validate_json(row[0]).normalize(clock) for row in rows]
        keys = {(r.bar.tf, r.t_open_ms) for r in records}
        if len(keys) != len(records):
            raise ValueError("HALTED: clock projection creates duplicate UTC bars")
        self.db.execute("BEGIN TRANSACTION")
        try:
            legacy = self.db.execute(
                "SELECT count(*) FROM bars WHERE broker=? AND source='mt5' AND t_broker_ms IS NULL",
                [self.broker],
            ).fetchone()
            if legacy and legacy[0]:
                raise ValueError(
                    "Legacy MT5 bars lack raw epochs; reacquire them before clock reconstruction"
                )
            self.db.execute("DELETE FROM bars WHERE broker=? AND source='mt5'", [self.broker])
            if records:
                self.db.execute(
                    "INSERT OR REPLACE INTO bars SELECT unnest(?),unnest(?),unnest(?),unnest(?),unnest(?),unnest(?),unnest(?)",
                    [
                        [self.broker] * len(records),
                        [r.bar.tf for r in records],
                        [r.t_open_ms for r in records],
                        ["mt5"] * len(records),
                        [r.bar.canonical_json() for r in records],
                        [r.t_broker_ms for r in records],
                        [r.clock_version for r in records],
                    ],
                )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.active_clock_version = clock.version
        return len(records)

    @serialized_write
    def put(self, bar: Bar) -> bool:
        old = self.db.execute(
            "SELECT source, t_broker_ms FROM bars WHERE broker=? AND tf=? AND t=?",
            [self.broker, bar.tf, bar.t_open_ms],
        ).fetchone()
        if old and old[0] == "mt5" and bar.source != "mt5":
            return False
        if old and old[1] is not None:
            # A tick builder must not erase already verified broker provenance.
            return False
        self.db.execute(
            "INSERT OR REPLACE INTO bars (broker, tf, t, source, payload) VALUES (?, ?, ?, ?, ?)",
            [self.broker, bar.tf, bar.t_open_ms, bar.source, bar.canonical_json()],
        )
        return True

    def read(self, tf: Timeframe, start_ms: int, end_ms: int) -> list[Bar]:
        if self.active_clock_version is not None:
            stale = self.db.execute(
                "SELECT count(*) FROM bars WHERE broker=? AND tf=? AND clock_version IS NOT NULL AND clock_version != ?",
                [self.broker, tf, self.active_clock_version],
            ).fetchone()
            if stale and stale[0]:
                raise ValueError("clock changed, reconstruct UTC projection before reading bars")
        rows = self.db.execute(
            "SELECT payload, clock_version FROM bars WHERE broker=? AND tf=? AND t>=? AND t<? ORDER BY t",
            [self.broker, tf, start_ms, end_ms],
        ).fetchall()
        if self.active_clock_version is not None and any(
            row[1] is not None and row[1] != self.active_clock_version for row in rows
        ):
            raise ValueError("clock changed, reconstruct UTC projection before reading bars")
        return [Bar.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        self.db.close()
