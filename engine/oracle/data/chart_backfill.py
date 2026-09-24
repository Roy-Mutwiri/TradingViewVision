"""Background calendar/backfill owner. No command-handler or shared DB connection."""

import logging
import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oracle.data.auth_session import LoginGate
from oracle.data.backfill import backfill_step
from oracle.data.broker_bar import RawBrokerBar
from oracle.data.calendar import derive_calendar, save_calendar
from oracle.data.clock_derivation import derive_history_clock
from oracle.data.mt5_gateway import Mt5Gateway
from oracle.models import Timeframe

log = logging.getLogger(__name__)
TFS: tuple[Timeframe, ...] = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1")


class ChartBackfill:
    def __init__(self, gate: LoginGate) -> None:
        assert gate.feed and gate.feed.store and gate.feed.clock and gate.feed.instrument
        self.feed = gate.feed
        self.store = gate.feed.store.fork()
        self.events: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self.stop = threading.Event()
        self.foreground_queue: queue.SimpleQueue[tuple[Timeframe, int, int]] = queue.SimpleQueue()
        self.tf: Timeframe = "M5"
        self.requested: dict[Timeframe, int] = {}
        self.thread = threading.Thread(target=self._run, name="oracle-backfill", daemon=True)
        self.thread.start()

    def request_foreground(self, tf: Timeframe, count: int, earliest_utc_ms: int) -> None:
        if self.requested.get(tf) == earliest_utc_ms:
            return
        self.requested[tf] = earliest_utc_ms
        self.foreground_queue.put((tf, count, earliest_utc_ms))

    def _run(self) -> None:
        api = self.feed.api
        assert isinstance(api, Mt5Gateway) and self.feed.clock and self.feed.instrument
        last_derivation = 0
        prefetched: set[Timeframe] = set()
        exhausted: set[Timeframe] = set()
        try:
            while not self.stop.is_set():
                clock = self.feed.clock
                assert clock is not None
                while not self.foreground_queue.empty():
                    tf, required, earliest = self.foreground_queue.get()
                    with api.foreground():
                        rows = api.copy_rates_from(
                            self.feed.broker_symbol,
                            getattr(api, f"TIMEFRAME_{tf}"),
                            datetime.fromtimestamp(
                                (earliest + self.feed.server_utc_offset_s * 1000 - 1) / 1000, UTC
                            ),
                            required,
                        )
                    raw = [
                        RawBrokerBar.model_validate(
                            self.feed._row(r, True).model_dump() | {"tf": tf}
                        )
                        for r in (rows if rows is not None else [])
                    ]
                    for i in range(0, len(raw), 250):
                        self.store.put_broker_many([b.normalize(clock) for b in raw[i : i + 250]])
                    self.events.put({"filled_tf": tf})
                index = TFS.index(self.tf)
                neighbors = TFS[max(0, index - 1) : index + 2]
                # Adjacent snapshots have a separate small bulk allocation.
                for tf in neighbors:
                    if tf in prefetched or self.stop.is_set():
                        continue
                    with api.priority(api.PRIORITY_BULK):
                        rows = api.copy_rates_from_pos(
                            self.feed.broker_symbol, getattr(api, f"TIMEFRAME_{tf}"), 0, 2000
                        )
                    raw = [
                        self.feed._row(row, i < len(rows) - 1).model_copy(update={"tf": tf})
                        for i, row in enumerate(rows if rows is not None else [])
                    ]
                    for i in range(0, len(raw), 250):
                        self.store.put_broker_many([b.normalize(clock) for b in raw[i : i + 250]])
                    prefetched.add(tf)
                    self.events.put({"filled_tf": tf})
                oldest = self.store.earliest_fetched(self.feed.broker_symbol, "M1")
                now = time.time_ns() // 1000000
                pending = "M1" not in exhausted and (
                    oldest is None or clock.utc_ms(oldest) > now - 180 * 86400000
                )
                if pending:
                    found = backfill_step(
                        api,
                        self.store,
                        clock,
                        self.feed.broker_symbol,
                        "M1",
                        now + self.feed.server_utc_offset_s * 1000,
                        self.feed.instrument.digits,
                    )
                    if found < 1000:
                        exhausted.add("M1")
                        pending = False
                count_row = self.store.db.execute(
                    "SELECT count(*),min(t),max(t) FROM bars WHERE broker=? AND tf='M1' AND source='mt5'",
                    [self.store.broker],
                ).fetchone()
                count, first, last = count_row if count_row else (0, None, None)
                detail = (
                    f"Calendar downloading: {count:,} M1 bars received"
                    if pending
                    else f"Calendar history available: {count:,} M1 bars"
                )
                self.events.put({"detail": detail, "pending": pending})
                # Expensive derivation runs here, never on the MT5 or IPC thread.
                if count > 1 and (
                    not last_derivation
                    or count - last_derivation >= 30000
                    or not pending
                    and count != last_derivation
                ):
                    bars = self.store.read("M1", max(0, now - 180 * 86400000), now)
                    if len(bars) > 1:
                        calendar = derive_calendar(bars, clock)
                        predicted = [
                            c.model_copy(
                                update={
                                    "start_ms": c.start_ms + 7 * 86400000,
                                    "end_ms": c.end_ms + 7 * 86400000,
                                }
                            )
                            for c in calendar.closures
                            if c.recurring and c.start_ms >= calendar.valid_to_ms - 7 * 86400000
                        ]
                        calendar = calendar.model_copy(
                            update={
                                "valid_to_ms": calendar.valid_to_ms + 7 * 86400000,
                                "closures": calendar.closures + tuple(predicted),
                            }
                        )
                        self.events.put(
                            {
                                "calendar": calendar,
                                "pending": pending,
                                "detail": f"Derived calendar from {(bars[-1].t_open_ms - bars[0].t_open_ms) // 86400000} days; bulk history {'continuing' if pending else 'complete'}",
                            }
                        )
                        save_calendar(
                            calendar,
                            Path(self.feed.config.broker_clock_path).with_name("sessions.yaml"),
                        )
                    last_derivation = count
                if first is not None and last - first >= 30 * 86400000:
                    if self.feed.vendor is None:
                        self.events.put(
                            {
                                "refinement_pending": "Clock transition derivation pending: independent UTC feed is not configured"
                            }
                        )
                    elif not pending:
                        raw = [b for b in self.store.raw_history("M1") if b.complete]
                        refined = derive_history_clock(
                            raw,
                            self.feed.vendor,
                            clock.broker,
                            self.feed.config.expected_offset_s,
                            self.feed.server_utc_offset_s,
                            clock,
                        )
                        if refined.version != clock.version:
                            self.events.put({"refined": refined})
                            break
                self.stop.wait(0.05 if pending else 2)
        except Exception as exc:
            log.warning("Background history paused: %s", type(exc).__name__)
            self.events.put(
                {
                    "detail": "Background history paused; live quotes continue. Retry from preflight.",
                    "background_error": type(exc).__name__,
                }
            )
        finally:
            self.store.close()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
