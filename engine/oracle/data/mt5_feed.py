"""MT5 boundary: preserve raw wall-clock epochs before UTC projection."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from oracle.config import DataConfig
from oracle.data.broker_bar import BrokerBar, RawBrokerBar
from oracle.data.broker_clock import BrokerClock, OffsetSpan, derive_offset
from oracle.data.candle_store import CandleStore
from oracle.data.clock_alignment import (
    CANDIDATE_OFFSETS,
    AlignmentReport,
    assert_alignment,
    correlate_offsets,
)
from oracle.data.instrument import Instrument
from oracle.data.symbol_policy import assert_gold_symbol
from oracle.models import Bar, Timeframe, timeframe_ms
from oracle.transport.chart import TickQuote

log = logging.getLogger(__name__)


class UTCFeed(Protocol):
    def history(self, tf: Timeframe, start_ms: int, end_ms: int) -> list[Bar]: ...


class MT5Feed:
    def __init__(
        self,
        api: Any,
        config: DataConfig,
        vendor: UTCFeed | None = None,
        store: CandleStore | None = None,
        allow_unproven: bool = False,
    ) -> None:
        self.api, self.config, self.vendor = api, config, vendor
        self.allow_unproven = allow_unproven
        self.store = store
        self.clock: BrokerClock | None = None
        self.instrument: Instrument | None = None
        self.server_utc_offset_s = 0
        self.broker_symbol = ""
        self.vendor_verified = False

    def startup(self) -> Instrument:
        if not self.config.canonical_broker.strip():
            raise ValueError("Pin canonical_broker before ingestion")
        if not self.api.initialize(
            **({"path": self.config.mt5_path} if self.config.mt5_path else {})
        ):
            raise RuntimeError("MT5 initialization failed")
        account = self.api.account_info()
        if account is None:
            raise ValueError("HALTED: MT5 account unavailable")
        # A broker name is not a server-group name (e.g. Exness-MT5Real...).
        brand = self.config.canonical_broker.casefold()
        if (
            not str(account.server).split("-", 1)[0].casefold().startswith(brand)
            and str(account.server).casefold() != brand
        ):
            raise ValueError("HALTED: connected MT5 server differs from canonical broker")
        if self.config.canonical_server and account.server != self.config.canonical_server:
            raise ValueError("HALTED: connected MT5 server differs from pinned server group")
        available = {s.name for s in self.api.symbols_get() or ()}
        self.broker_symbol = next(
            (s for s in self.config.broker_symbol_patterns if s in available), ""
        )
        assert_gold_symbol(self.broker_symbol)
        if not self.broker_symbol or not self.api.symbol_select(self.broker_symbol, True):
            raise ValueError("HALTED: cannot resolve/select canonical instrument")
        self.instrument = Instrument.from_mt5(self.api.symbol_info(self.broker_symbol))
        if self.store is None:
            Path(self.config.store_path).parent.mkdir(parents=True, exist_ok=True)
            self.store = CandleStore(self.config.store_path, self.config.canonical_broker)
        self.store.bind_server(str(account.server))
        path = Path(self.config.broker_clock_path)
        if path.exists():
            self.clock = BrokerClock.load(path)
            self.clock.assert_expected(self.config.canonical_broker, self.config.expected_offset_s)
        self.refresh_offset(startup=True)
        terminal = self.api.terminal_info()
        if terminal and terminal.maxbars < 2147483647:
            log.warning("Set Tools > Options > Charts > Max bars in chart to Unlimited")
        log.info(
            "Exness D1/W1 broker boundaries differ from the analytical New York rollover by design; use them for HTF structure only"
        )
        return self.instrument

    def refresh_offset(self, startup: bool = False) -> None:
        tick = self.api.symbol_info_tick(self.broker_symbol)
        if tick is None:
            raise RuntimeError("No tick available to verify clock")
        now_s = time.time()
        if self.clock is not None:
            from oracle.data.assumed_calendar import assumed_closed
            tick_ms = int(tick.time) * 1000
            tick_utc_ms = self.clock.utc_ms(tick_ms)
            if now_s * 1000 - tick_utc_ms > 120000 and assumed_closed(int(now_s * 1000)):
                self.clock.assert_expected(self.config.canonical_broker, self.config.expected_offset_s)
                if self.clock.server != str(self.api.account_info().server):
                    raise ValueError("HALTED: broker clock server differs from connected account")
                self.vendor_verified = False
                return  # A frozen last tick cannot measure the current broker clock.
        offset = derive_offset(int(tick.time), now_s)
        if offset not in self.config.expected_offset_s:
            raise ValueError(
                f"HALTED: offset {offset}s is outside canonical broker expected offsets"
            )
        effective = int(tick.time) * 1000 // 60000 * 60000
        candidate = (
            self.clock.measured(effective, offset)
            if self.clock
            else BrokerClock(
                broker=self.config.canonical_broker,
                server=str(self.api.account_info().server),
                spans=(
                    OffsetSpan(
                        from_broker_ms=None,
                        to_broker_ms=None,
                        offset_s=offset,
                        confidence="MEASURED",
                    ),
                ),
                measured_from_broker_ms=int(getattr(tick, "time_msc", int(tick.time) * 1000)),
                version=1,
                derivation="measured",
            )
        )
        server = str(self.api.account_info().server)
        if candidate.server and candidate.server != server:
            raise ValueError("HALTED: broker clock server differs from connected account")
        candidate = candidate.model_copy(update={"server": server})
        changed = self.clock is None or candidate != self.clock
        if startup or changed:
            self.vendor_verified = False
            log.info(
                "Broker clock startup/change: broker=%s offset_s=%s clock_version=%s",
                candidate.broker,
                offset,
                candidate.version,
            )
            if self.vendor is not None:
                first_verified_ms = self._verify_live(offset)
                log.info(
                    "Independent UTC sample proven from broker_ms=%s; historical refinement remains background work",
                    first_verified_ms,
                )
                self.vendor_verified = True
        self.clock = candidate
        if self.store is not None:
            if (
                self.store.active_clock_version is not None
                and self.store.active_clock_version != candidate.version
            ):
                self.store.reproject(candidate)
            self.store.expect_clock(candidate)
        self.server_utc_offset_s = offset
        if startup or changed:
            candidate.save(Path(self.config.broker_clock_path))
            log.info(
                "Broker clock active: broker=%s offset_s=%s clock_version=%s",
                candidate.broker,
                offset,
                candidate.version,
            )

    def _row(self, row: Any, complete: bool) -> RawBrokerBar:
        if self.instrument is None:
            raise RuntimeError("Load instrument before clock conversion")
        return RawBrokerBar(
            tf="M1",
            t_broker_ms=int(row["time"]) * 1000,
            o=float(row["open"]),
            h=float(row["high"]),
            l=float(row["low"]),
            c=float(row["close"]),
            tick_volume=int(row["tick_volume"]),
            digits=self.instrument.digits,
            complete=complete,
        )

    def _verify_live(self, measured_offset: int) -> int:
        if self.vendor is None or self.store is None:
            raise RuntimeError("Independent UTC feed and raw archive required")
        # Leave enough history after the sample to evaluate negative offsets without
        # requesting future UTC bars. Position 1 is the most recent closed minute.
        position = 1 + (max(self.config.expected_offset_s) - min(CANDIDATE_OFFSETS)) // 60
        rows = self.api.copy_rates_from_pos(
            self.broker_symbol, self.api.TIMEFRAME_M1, position, 500
        )
        if rows is None or len(rows) < 500:
            raise RuntimeError("HALTED: 500 closed MT5 M1 bars required for startup correlation")
        raw = [self._row(row, True) for row in rows]
        for bar in raw:
            self.store.archive_raw(bar)
        vendor = self.vendor.history(
            "M1",
            raw[0].t_broker_ms - max(CANDIDATE_OFFSETS) * 1000,
            raw[-1].t_broker_ms - min(CANDIDATE_OFFSETS) * 1000 + 60000,
        )
        report = correlate_offsets(raw, vendor)
        if report.offset_s != measured_offset:
            raise ValueError(
                f"HALTED: vendor UTC alignment wins at {report.offset_s}s; live measurement was {measured_offset}s"
            )
        log.info(
            "Broker clock UTC proof: offset_s=%s OHLC_correlation=%.6f samples=%s",
            report.offset_s,
            report.correlation,
            report.samples,
        )
        return raw[0].t_broker_ms

    def raw_history(
        self, tf: Timeframe, start_broker_ms: int, end_broker_ms: int
    ) -> list[RawBrokerBar]:
        if self.instrument is None or self.store is None:
            raise RuntimeError("Startup required before raw history acquisition")
        if tf == "MN1":
            raise ValueError("Calendar-month ingestion requires calendar arithmetic")
        deadline, delay = time.monotonic() + 30, 0.25
        rows: Any = None
        while True:
            rows = self.api.copy_rates_range(
                self.broker_symbol,
                getattr(self.api, f"TIMEFRAME_{tf}"),
                datetime.fromtimestamp(start_broker_ms / 1000, UTC),
                datetime.fromtimestamp((end_broker_ms - 1) / 1000, UTC),
            )
            if rows is not None and len(rows) and int(rows[0]["time"]) * 1000 <= start_broker_ms:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning(
                    "Short/empty history for %s; check Unlimited chart history; calendar must validate gaps",
                    tf,
                )
                break
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, 4)
        result: list[RawBrokerBar] = []
        if rows is None:
            return result
        now_broker_ms = time.time_ns() // 1000000 + self.server_utc_offset_s * 1000
        for i, row in enumerate(rows):
            raw = self._row(
                row,
                i < len(rows) - 1
                or now_broker_ms
                >= int(row["time"]) * 1000 + timeframe_ms(tf) + self.config.grace_ms,
            )
            raw = RawBrokerBar.model_validate(raw.model_dump() | {"tf": tf})
            if start_broker_ms <= raw.t_broker_ms < end_broker_ms:
                self.store.archive_raw(raw)
                result.append(raw)
        return result

    def _require_projection(self) -> tuple[BrokerClock, CandleStore]:
        if self.clock is None or self.store is None:
            raise RuntimeError("Clock and store must initialize before normalized ingestion")
        return self.clock, self.store

    def history(
        self, tf: Timeframe, start_ms: int, end_ms: int, instrument: Instrument
    ) -> list[Bar]:
        if instrument != self.instrument:
            raise ValueError("Instrument differs from startup metadata")
        self.refresh_offset()
        clock, store = self._require_projection()
        minimum, maximum = min(self.config.expected_offset_s), max(self.config.expected_offset_s)
        raw = self.raw_history(tf, start_ms + minimum * 1000, end_ms + maximum * 1000)
        result = []
        for item in raw:
            record = item.normalize(clock)
            if start_ms <= record.t_open_ms < end_ms:
                store.put_broker(record)
                result.append(record.bar)
        return result

    def broker_minute_record(self, t_open_ms: int, refresh: bool = True) -> BrokerBar:
        if refresh:
            self.refresh_offset()
        clock, store = self._require_projection()
        rows = self.api.copy_rates_from_pos(self.broker_symbol, self.api.TIMEFRAME_M1, 0, 3)
        if rows is not None:
            for i, row in enumerate(rows):
                raw = self._row(
                    row,
                    i < len(rows) - 1
                    or time.time_ns() // 1000000
                    >= clock.utc_ms(int(row["time"]) * 1000) + 60000 + self.config.grace_ms,
                )
                store.archive_raw(raw)
                record = raw.normalize(clock)
                if record.t_open_ms == t_open_ms:
                    return record
        archived = store.db.execute(
            "SELECT payload FROM raw_bars WHERE broker=? AND tf='M1' AND t_broker_ms IN (SELECT t_broker_ms FROM bars WHERE broker=? AND tf='M1' AND t=?)",
            [store.broker, store.broker, t_open_ms],
        ).fetchone()
        if archived:
            raw = RawBrokerBar.model_validate_json(archived[0])
            if raw.complete:
                return raw.normalize(clock)
        for offset in {s.offset_s for s in clock.spans}:
            candidate = t_open_ms + offset * 1000
            if clock.utc_ms(candidate) != t_open_ms:
                continue
            rows = self.api.copy_rates_from(
                self.broker_symbol,
                self.api.TIMEFRAME_M1,
                datetime.fromtimestamp(candidate / 1000, UTC),
                1,
            )
            for row in rows if rows is not None else []:
                raw = self._row(row, True)
                if clock.utc_ms(raw.t_broker_ms) == t_open_ms:
                    store.archive_raw(raw)
                    return raw.normalize(clock)
        from oracle.transport.errors import EngineError

        raise EngineError(
            "BAR_RECONCILIATION_PENDING",
            "The broker has not supplied this closed minute yet; live quotes continue while history retries.",
            {"t_open_ms": t_open_ms, "symbol": self.broker_symbol, "clock_version": clock.version},
        )

    def tick_quote(self) -> "TickQuote | None":
        from oracle.data.mt5_gateway import Mt5Gateway
        from oracle.models import Quote

        if not isinstance(self.api, Mt5Gateway) or self.clock is None or self.instrument is None:
            return None
        tick, received = self.api.cached_quote()
        if tick is None or received == 0:
            return None
        return TickQuote(
            quote=Quote(
                symbol="XAUUSD",
                bid=float(tick.bid),
                ask=float(tick.ask),
                t_ms=self.clock.utc_ms(int(tick.time_msc)),
                source="mt5",
            ),
            received_ms=received,
            now_ms=time.time_ns() // 1000000,
            digits=self.instrument.digits,
            spread_points=(float(tick.ask) - float(tick.bid)) / self.instrument.point,
        )

    def broker_minute(self, t_open_ms: int, instrument: Instrument) -> Bar:
        if instrument != self.instrument:
            raise ValueError("Instrument differs from startup metadata")
        record = self.broker_minute_record(t_open_ms)
        assert self.store is not None
        self.store.put_broker(record)
        return record.bar

    def verify_history_window(self, raw: list[RawBrokerBar]) -> AlignmentReport:
        if self.vendor is None or self.clock is None:
            raise RuntimeError("Clock and independent UTC vendor feed required")
        if len(raw) < 500:
            raise ValueError("Seasonal proof requires 500 raw M1 bars")
        vendor = self.vendor.history(
            "M1",
            raw[0].t_broker_ms - max(CANDIDATE_OFFSETS) * 1000,
            raw[499].t_broker_ms - min(CANDIDATE_OFFSETS) * 1000 + 60000,
        )
        report = correlate_offsets(raw, vendor)
        assert_alignment(report, self.clock, raw)
        return report

