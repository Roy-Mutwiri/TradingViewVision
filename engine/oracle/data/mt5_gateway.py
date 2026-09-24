"""The sole MT5 SDK boundary: one terminal thread, priority calls and cached ticks."""

from __future__ import annotations

import importlib
import itertools
import logging
import queue
import threading
import time
from collections import deque
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

from oracle.models import TF_MS

log = logging.getLogger(__name__)


class Mt5Gateway:
    PRIORITY_TICK = 0
    PRIORITY_FOREGROUND = 1
    PRIORITY_BULK = 2
    MAX_BARS = 5000
    METHODS = frozenset(
        {
            "initialize",
            "shutdown",
            "last_error",
            "account_info",
            "terminal_info",
            "symbols_get",
            "symbol_select",
            "symbol_info",
            "symbol_info_tick",
            "copy_rates_from_pos",
            "copy_rates_from",
            "copy_rates_range",
            "copy_ticks_from",
        }
    )

    def __init__(self, module: Any = None, tick_poll_ms: int = 50) -> None:
        self._module = module if module is not None else importlib.import_module("MetaTrader5")
        self._queue: queue.PriorityQueue[
            tuple[int, int, float, str, tuple[Any, ...], dict[str, Any], Future[Any]]
        ] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._local = threading.local()
        self._lock = threading.Lock()
        self._ticks: deque[Any] = deque(maxlen=20000)
        self._quote: Any = None
        self._quote_received_ms = 0
        self._symbol: str | None = None
        self._interval = tick_poll_ms / 1000
        self._paused = 0
        self._stopped = threading.Event()
        self._metrics = {
            p: {"calls": 0, "wait_ms": 0.0, "call_ms": 0.0, "queue_depth": 0} for p in range(3)
        }
        self._depth = {p: 0 for p in range(3)}
        self._bulk_limit = 1000
        self._tick_latency_ms = 0.0
        self._latencies: deque[tuple[float, float]] = deque(maxlen=200)
        self._thread = threading.Thread(target=self._run, name="oracle-mt5", daemon=True)
        self._thread.start()

    @contextmanager
    def priority(self, priority: int) -> Iterator[None]:
        previous = getattr(self._local, "priority", self.PRIORITY_FOREGROUND)
        self._local.priority = priority
        try:
            yield
        finally:
            self._local.priority = previous

    @contextmanager
    def foreground(self) -> Iterator[None]:
        with self._lock:
            self._paused += 1
        try:
            with self.priority(self.PRIORITY_FOREGROUND):
                yield
        finally:
            with self._lock:
                self._paused -= 1

    def watch(self, symbol: str) -> None:
        with self._lock:
            self._symbol = symbol
            self._ticks.clear()
            self._quote = None

    def quote(self) -> Any:
        with self._lock:
            return self._quote

    def quote_received_ms(self) -> int:
        with self._lock:
            return self._quote_received_ms

    def cached_quote(self) -> tuple[Any, int]:
        with self._lock:
            return self._quote, self._quote_received_ms

    def drain_ticks(self) -> list[Any]:
        with self._lock:
            ticks = list(self._ticks)
            self._ticks.clear()
        return ticks

    def telemetry(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            recent = [value for measured, value in self._latencies if now - measured <= 5]
            return {
                "priorities": {
                    str(p): dict(v) | {"queue_depth": self._depth[p]}
                    for p, v in self._metrics.items()
                },
                "tick_latency_ms": max(recent, default=self._tick_latency_ms),
                "queue_depth": self._queue.qsize(),
            }

    def _submit(
        self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any], priority: int
    ) -> Any:
        if self._stopped.is_set():
            raise RuntimeError("MT5 gateway is closed")
        future: Future[Any] = Future()
        with self._lock:
            self._depth[priority] += 1
        self._queue.put(
            (priority, next(self._sequence), time.monotonic(), name, args, kwargs, future)
        )
        return future.result()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("TIMEFRAME_") or name == "COPY_TICKS_ALL":
            return getattr(self._module, name)
        if name not in self.METHODS:
            raise AttributeError("Operation unavailable in read-only MT5 gateway")

        def call(*args: Any, **kwargs: Any) -> Any:
            priority = (
                self.PRIORITY_TICK
                if name == "symbol_info_tick"
                else getattr(self._local, "priority", self.PRIORITY_FOREGROUND)
            )
            limit = self._bulk_limit if priority == self.PRIORITY_BULK else self.MAX_BARS
            if name == "shutdown":
                with self._lock:
                    self._symbol = None
                    self._ticks.clear()
                    self._quote = None
            if (
                name in ("copy_rates_from_pos", "copy_rates_from")
                and len(args) >= 4
                and args[3] > limit
            ):
                result: list[Any] = []
                remaining, cursor = int(args[3]), args[2]
                while remaining:
                    amount = min(
                        remaining, self._bulk_limit if priority == self.PRIORITY_BULK else limit
                    )
                    rows = self._submit(name, (*args[:2], cursor, amount), kwargs, priority)
                    if rows is None or not len(rows):
                        break
                    result.extend(rows)
                    remaining -= len(rows)
                    if len(rows) < amount:
                        break
                    cursor = (
                        cursor + len(rows)
                        if name.endswith("pos")
                        else datetime.fromtimestamp(int(rows[0]["time"]) - 1, UTC)
                    )
                return sorted(result, key=lambda r: int(r["time"]))
            if name == "copy_rates_range" and len(args) >= 4:
                duration = next(
                    (
                        ms
                        for tf, ms in TF_MS.items()
                        if ms and getattr(self._module, f"TIMEFRAME_{tf}", None) == args[1]
                    ),
                    None,
                )
                if duration:
                    result = []
                    start, end = args[2].timestamp(), args[3].timestamp()
                    stride = limit * duration / 1000
                    while start <= end:
                        stop = min(end, start + stride - 1)
                        rows = self._submit(
                            name,
                            (
                                *args[:2],
                                datetime.fromtimestamp(start, UTC),
                                datetime.fromtimestamp(stop, UTC),
                            ),
                            kwargs,
                            priority,
                        )
                        if rows is not None:
                            result.extend(rows)
                        start += stride
                    return result
            return self._submit(name, args, kwargs, priority)

        return call

    def _record(self, priority: int, queued: float, started: float, ended: float) -> None:
        with self._lock:
            self._metrics[priority] = {
                "calls": self._metrics[priority]["calls"] + 1,
                "wait_ms": (started - queued) * 1000,
                "call_ms": (ended - started) * 1000,
                "queue_depth": self._queue.qsize(),
            }

    def _run(self) -> None:
        due, logged = time.monotonic(), time.monotonic()
        while not self._stopped.is_set():
            now = time.monotonic()
            if self._symbol and now >= due:
                expected = due
                try:
                    tick = self._module.symbol_info_tick(self._symbol)
                    ended = time.monotonic()
                    with self._lock:
                        previous = self._quote
                        self._quote = tick
                        self._tick_latency_ms = max(0.0, (ended - expected) * 1000)
                        self._latencies.append((ended, self._tick_latency_ms))
                        if tick and (
                            previous is None
                            or (tick.time_msc, tick.bid, tick.ask)
                            != (previous.time_msc, previous.bid, previous.ask)
                        ):
                            self._quote_received_ms = time.time_ns() // 1000000
                            self._ticks.append(tick)
                    self._record(0, expected, now, ended)
                except Exception:
                    log.warning("MT5 quote polling failed; terminal connection requires attention")
                due = time.monotonic() + self._interval
            if now - logged >= 5:
                log.info("Mt5Gateway queue %s", self.telemetry())
                logged = now
            try:
                job = self._queue.get(
                    timeout=max(0.001, min(self._interval, due - time.monotonic()))
                    if self._symbol
                    else self._interval
                )
            except queue.Empty:
                continue
            priority, sequence, queued, name, args, kwargs, future = job
            if priority == self.PRIORITY_BULK and self._paused:
                self._queue.put(job)
                self._stopped.wait(0.001)
                continue
            started = time.monotonic()
            with self._lock:
                self._depth[priority] -= 1
            try:
                future.set_result(getattr(self._module, name)(*args, **kwargs))
            except Exception as exc:
                future.set_exception(exc)
            finally:
                ended = time.monotonic()
                self._record(priority, queued, started, ended)
                if priority == self.PRIORITY_BULK and ended - started > 0.2:
                    self._bulk_limit = max(25, self._bulk_limit // 2)
                    log.warning(
                        "MT5 bulk chunk exceeded 200ms: call=%s duration_ms=%s next_limit=%s",
                        name,
                        (ended - started) * 1000,
                        self._bulk_limit,
                    )
                args, kwargs = (), {}  # release transient credential-bearing arguments
                del job

    def close(self) -> None:
        self.shutdown()
        self._stopped.set()
        self._thread.join(timeout=2)
