"""Serialized terminal polling, UTC projection, and broker close reconciliation."""

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oracle.config import UTBotOverride
from oracle.data.aggregate import aggregate_m1
from oracle.data.assumed_calendar import assumed_closed, assumed_explains
from oracle.data.auth_session import LoginGate
from oracle.data.broker_bar import RawBrokerBar
from oracle.data.broker_clock import BrokerClock
from oracle.data.calendar import TradingCalendar
from oracle.data.candidate_service import CandidateService
from oracle.data.chart_backfill import ChartBackfill
from oracle.data.mt5_gateway import Mt5Gateway
from oracle.data.symbol_policy import assert_gold_symbol
from oracle.data.ticks import TickBuilder
from oracle.indicators.ut_bot import draw_ut_bot, ut_bot
from oracle.models import Animation, Bar, DataQuality, DrawObject, Point, Quote, Style, Timeframe, UTBotDrawObject, timeframe_ms
from oracle.smc.fvg_drawing import FVGDrawing
from oracle.thesis import build_thesis
from oracle.stats import compute_history_stats
from oracle.book import build_book, book_draw_objects
from oracle.transport.chart import (
    BarsSnapshot,
    BarUpdate,
    ChartDebug,
    ChartFrame,
    DebugBar,
    SessionClosure,
)
from oracle.transport.errors import EngineError


class LiveChart:
    def __init__(self, gate: LoginGate) -> None:
        gate.status()
        assert gate.feed and gate.feed.instrument and gate.feed.clock and gate.feed.store
        self.gate = gate
        self.feed = gate.feed
        assert self.feed.instrument
        self.tf: Timeframe = "M5"
        self.bars: dict[int, Bar] = {}
        self.debug_bars: dict[int, DebugBar] = {}
        self.calendar: TradingCalendar | None = None
        self.calendar_detail = "Calendar pending: downloading observed M1 history"
        self.builder = TickBuilder(self.feed.instrument.tick_size, self.feed.instrument.digits)
        self.cursor_ms = 0
        self.cursor_count = 0
        self.last_tick_ms = 0
        self.spread = 0.0
        self.last_poll = 0.0
        self.last_clock_check = 0.0
        self.closed_pending: dict[int, Bar] = {}
        self.reconcile_retry: dict[int, int] = {}
        self.reconciled: set[int] = set()
        self.detail = ""
        self.last_calendar_refresh = 0
        self.history_short = False
        self.refinement_pending = "Clock transition derivation pending: 30 days of M1 required"
        self.refinement_checked = False
        self.calendar_pending = True
        self.calendar_cursor = 0
        self.calendar_bars: dict[int, Bar] = {}
        self.refinement_retry_ms = 0
        self.switch_ms = 0.0
        self.bid = self.ask = 0.0
        self.last_bar_poll = 0.0
        self.missing_ranges: list[dict[str, int]] = []
        self.confirmed_ut: dict[str, UTBotDrawObject] = {}
        self.provisional_ut: set[str] = set()
        self.provisional_seen = self.provisional_confirmed = self.provisional_removed = 0
        self.indicator_detail: dict[str, Any] = {}
        self.ut_draw_cache: dict[Timeframe, tuple[object, list[UTBotDrawObject]]] = {}
        self.fvg_draw_cache: dict[Timeframe, FVGDrawing] = {}
        self.candidate_service = CandidateService(self.feed, gate.config) if gate.config.candidates.enabled else None
        self.backfill: ChartBackfill | None = None
        if isinstance(self.feed.api, Mt5Gateway):
            self.feed.api.watch(self.feed.broker_symbol)
            self.backfill = ChartBackfill(gate)

    def _rates(self, tf: Timeframe, count: int) -> list[Bar]:
        assert self.feed.clock and self.feed.store
        rows = self.feed.api.copy_rates_from_pos(
            self.feed.broker_symbol, getattr(self.feed.api, f"TIMEFRAME_{tf}"), 0, count
        )
        result = []
        records = []
        raw_bars = []
        for i, row in enumerate(rows if rows is not None else []):
            raw_ms = int(row["time"]) * 1000
            complete = i < len(rows) - 1 or (
                self.now()
                >= self.feed.clock.utc_ms(raw_ms)
                + timeframe_ms(tf)
                + self.gate.config.data.grace_ms
            )
            raw = self.feed._row(row, complete)
            raw = RawBrokerBar.model_validate(raw.model_dump() | {"tf": tf})
            raw_bars.append(raw)
        self.feed.store.archive_raw_many(raw_bars)
        for raw in raw_bars:
            record = raw.normalize(self.feed.clock)
            records.append(record)
            result.append(record.bar)
            if tf == self.tf:
                self.debug_bars[record.t_open_ms] = DebugBar(
                    t_open_ms=record.t_open_ms,
                    t_broker_ms=raw.t_broker_ms,
                    offset_s=self.feed.clock.offset_ms_at(raw.t_broker_ms) // 1000,
                    clock_version=self.feed.clock.version,
                    clock_confidence=self.feed.clock.confidence_at(raw.t_broker_ms),
                )
        self.feed.store.put_broker_many(records)
        return result

    def subscribe(self, tf: Timeframe) -> ChartFrame:
        if tf not in ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"):
            raise EngineError("TF_UNSUPPORTED", "Select a supported chart timeframe.", {"tf": tf})
        assert_gold_symbol(self.feed.broker_symbol)
        if self.feed.broker_symbol not in self.gate.config.data.broker_symbol_patterns:
            raise EngineError(
                "SYMBOL_UNRESOLVED",
                "No preferred spot gold symbol is selected; return to preflight and select XAUUSDz.",
                {
                    "symbol": self.feed.broker_symbol,
                    "candidates": list(self.gate.config.data.broker_symbol_patterns),
                },
            )
        started = time.perf_counter()
        if tf != self.tf:
            self.provisional_ut.clear()
        self.tf = tf
        if self.backfill:
            self.backfill.tf = tf
        assert self.feed.clock and self.feed.instrument
        self.debug_bars.clear()
        count = self.gate.config.chart.visible_bars + self.gate.config.chart.lookback
        assert self.feed.store
        bars = self.feed.store.latest(tf, count)
        if len(bars) < count:
            aggregated = aggregate_m1(
                self.feed.store,
                self.feed.clock,
                tf,
                count - len(bars),
                bars[0].t_open_ms if bars else None,
            )
            merged = {b.t_open_ms: b for b in aggregated}
            merged.update({b.t_open_ms: b for b in bars})  # Native broker bars win.
            bars = sorted(merged.values(), key=lambda b: b.t_open_ms)[-count:]
        if not bars:
            bars = self._rates(tf, count)
        # Warm switches return immediately; missing older ranges fill asynchronously.
        elif len(bars) < count and self.backfill:
            self.backfill.request_foreground(tf, count - len(bars), bars[0].t_open_ms)
        self._debug_from_store(tf, bars)
        if not bars:
            self.bars.clear()
            raise EngineError(
                "HISTORY_EMPTY",
                "MT5 returned no candles; open this symbol and timeframe in MT5 and scroll back to download history.",
                {
                    "symbol": self.feed.broker_symbol,
                    "tf": tf,
                    "requested": count,
                    "bars_found": 0,
                    "clock_version": self.feed.clock.version,
                },
            )
        self.bars = {b.t_open_ms: b for b in bars}
        self.history_short = len(bars) < count
        self.detail = f"{tf}: {len(bars)} / {count} requested chart bars" + (
            "; download history and set Max bars in chart to Unlimited"
            if self.history_short
            else ""
        )
        # Seed the current minute with the broker's full candle rather than a late first tick.
        minutes = self.feed.store.latest("M1", 2)
        if not minutes:
            minutes = self._rates("M1", 2)
        initializing = self.builder.current is None
        if minutes and initializing:
            self.builder.current = minutes[-1].transition(complete=False)
        tick = (
            self.feed.api.quote()
            if isinstance(self.feed.api, Mt5Gateway)
            else self.feed.api.symbol_info_tick(self.feed.broker_symbol)
        )
        if tick:
            if initializing:
                self.cursor_ms = int(tick.time_msc)
                self.cursor_count = 1
            self.last_tick_ms = self.feed.clock.utc_ms(self.cursor_ms)
            self.spread = (float(tick.ask) - float(tick.bid)) / self.feed.instrument.point
            self.bid, self.ask = float(tick.bid), float(tick.ask)
        self.switch_ms = (time.perf_counter() - started) * 1000
        self.last_bar_poll = time.monotonic()
        assert self.feed.store and self.feed.clock
        result = self.frame(
            "snapshot",
            snapshot=BarsSnapshot(tf=tf, bars=bars, clockVersion=self.feed.clock.version),
        )
        self.switch_ms = (time.perf_counter() - started) * 1000
        return result.model_copy(update={"switch_ms": self.switch_ms})

    def now(self) -> int:
        return time.time_ns() // 1000000

    def _closed(self) -> bool:
        return bool(
            self.calendar
            and self.calendar.valid_from_ms <= self.now() < self.calendar.valid_to_ms
            and not self.calendar.is_tradeable(self.now())
        )

    def _debug_from_store(self, tf: Timeframe, bars: list[Bar]) -> None:
        assert self.feed.store and self.feed.clock
        if not bars:
            return
        rows = self.feed.store.db.execute(
            "SELECT t,t_broker_ms,clock_version FROM bars WHERE broker=? AND tf=? AND t>=? AND t<=?",
            [self.feed.store.broker, tf, bars[0].t_open_ms, bars[-1].t_open_ms],
        ).fetchall()
        for t, raw, version in rows:
            if raw is not None:
                self.debug_bars[t] = DebugBar(
                    t_open_ms=t,
                    t_broker_ms=raw,
                    clock_version=version,
                    offset_s=self.feed.clock.offset_ms_at(raw) // 1000,
                    clock_confidence=self.feed.clock.confidence_at(raw),
                )

    def quality(self) -> DataQuality:
        age = max(0, self.now() - self.last_tick_ms)
        if not self.bars:
            return DataQuality(
                state="NO_DATA", staleness_ms=0, spread_points=self.spread, detail="data.no_data"
            )
        pending = self.calendar is None or self.calendar_pending
        closed = self._closed() or (
            (
                self.calendar is None
                or not self.calendar.valid_from_ms <= self.now() < self.calendar.valid_to_ms
            )
            and assumed_closed(self.now())
        )
        self.missing_ranges = []
        ordered = sorted(self.bars.values(), key=lambda b: b.t_open_ms)
        for a, b in zip(ordered, ordered[1:]):
            lo, hi = a.t_open_ms + timeframe_ms(self.tf), b.t_open_ms
            if hi <= lo:
                continue
            observed = (
                self.calendar is not None
                and self.calendar.valid_from_ms <= lo
                and hi <= self.calendar.valid_to_ms
            )
            explained = (
                self.calendar.explains(lo, hi)
                if observed and self.calendar
                else assumed_explains(lo, hi)
            )
            if not explained:
                self.missing_ranges.append({"from_ms": lo, "to_ms": hi})
        state: Any = "CALENDAR_PENDING" if pending else "OK"
        latency = (
            self.feed.api.telemetry()["tick_latency_ms"]
            if isinstance(self.feed.api, Mt5Gateway)
            else 0
        )
        if (
            age > self.gate.config.data.stale_ms
            or latency > self.gate.config.data.max_tick_latency_ms
        ) and not closed:
            state = "STALE"
        elif self.spread > self.gate.config.data.max_spread_points:
            state = "WIDE_SPREAD"
        elif self.missing_ranges:
            state = "GAPPED"
        return DataQuality(
            state=state,
            staleness_ms=age,
            spread_points=self.spread,
            detail="data.closed"
            if closed
            else "data.gapped"
            if self.missing_ranges
            else "data.calendar_pending"
            if pending
            else "data.live",
        )

    def _indicator_objects(self) -> list[UTBotDrawObject]:
        settings = self.gate.config.indicators.ut_bot.for_tf(self.tf)
        if not settings.enabled:
            self.provisional_ut.clear()
            self.indicator_detail = {"enabled": False, "warmup_bars": 3 * settings.atr_period}
            return []
        ordered = sorted(self.bars.values(), key=lambda b: b.t_open_ms)
        # A prior process can leave a historical forming snapshot in the local
        # store. It is useful as a grey fallback candle, but it must never enter
        # an indicator series where only the current tail may be provisional.
        bars = [bar for bar in ordered if bar.complete]
        if ordered and not ordered[-1].complete:
            bars.append(ordered[-1])
        values = ut_bot(bars, settings.key, settings.atr_period, settings.heikin_ashi, False)
        closed = bars if bars and bars[-1].complete else bars[:-1]
        signature = (
            closed[0].id if closed else None,
            closed[-1].id if closed else None,
            len(closed),
            settings.canonical_json(),
        )
        cached = self.ut_draw_cache.get(self.tf)
        if cached is None or cached[0] != signature:
            historical = draw_ut_bot(
                closed,
                settings,
                values[: len(closed)],
                limit=max(settings.label_budget, len(closed)),
            )
            self.ut_draw_cache[self.tf] = (signature, historical)
        else:
            historical = cached[1]
        preview = (
            draw_ut_bot(bars[-1:], settings, values[-1:], limit=1)
            if bars and not bars[-1].complete
            else []
        )
        current = historical + [o.transition(source_bars=[len(bars) - 1]) for o in preview]
        provisional = {o.id for o in current if not o.confirmed}
        confirmed = {o.id for o in current if o.confirmed}
        self.provisional_seen += len(provisional - self.provisional_ut)
        settled = self.provisional_ut - provisional
        self.provisional_confirmed += len(settled & confirmed)
        self.provisional_removed += len(settled - confirmed)
        self.provisional_ut = provisional
        for obj in current:
            if obj.confirmed:
                self.confirmed_ut.setdefault(
                    obj.id, obj
                )  # Confirmed calls are never withdrawn intrabar.
        prior = [o for o in self.confirmed_ut.values() if o.tf == self.tf]
        prior.sort(key=lambda o: o.t_open_ms)
        retained = {bar.t_open_ms for bar in bars}
        for old in [o for o in prior if o.t_open_ms not in retained]:
            self.confirmed_ut.pop(old.id, None)
        prior = [o for o in prior if o.t_open_ms in retained]
        output = prior + [o for o in current if not o.confirmed]
        self.indicator_detail = {
            "enabled": True,
            "warmup_bars": 3 * settings.atr_period,
            "warmup_from_ms": bars[0].t_open_ms if bars else None,
            "provisional": self.provisional_seen,
            "confirmed": self.provisional_confirmed,
            "removed": self.provisional_removed,
            "conversion_rate": self.provisional_confirmed / self.provisional_seen
            if self.provisional_seen
            else None,
            "key": settings.key,
            "atr_period": settings.atr_period,
            "show_stop_line": settings.show_stop_line,
            "color_bars": settings.color_bars,
            "bar_colors": [
                {"t_ms": b.t_open_ms, "token": "utbot.buy" if v.barbuy else "utbot.sell"}
                for b, v in zip(bars, values)
                if not v.warmup and settings.color_bars
            ],
        }
        if settings.show_stop_line:
            points = [
                {"t_ms": b.t_open_ms, "price": v.stop}
                for b, v in zip(bars, values)
                if not v.warmup and v.stop is not None and v.stop > 0
            ]
            if points:
                output.append(
                    UTBotDrawObject(
                        tf=self.tf,
                        t_open_ms=bars[0].t_open_ms,
                        direction="NEUTRAL",
                        layer="L2",
                        shape="PATH",
                        points=[Point.model_validate(p) for p in points],
                        style=Style(token="utbot.stop"),
                        text_key="indicator.utbot.stop",
                        text_args={},
                        state="FRESH",
                        ttl_ms=0,
                        priority=0,
                        z=0,
                        anim=Animation(in_="none", loop=None),
                        source_bars=[3 * settings.atr_period],
                        confidence=0,
                        reason="UT Bot ATR trailing stop",
                        digits=bars[0].digits,
                    )
                )
        if bars and values and not values[-1].warmup:
            latest_bar = bars[-1]
            latest_value = values[-1]
            if latest_value.barbuy or latest_value.barsell:
                direction = "BULLISH" if latest_value.barbuy else "BEARISH"
                token = "utbot.buy" if latest_value.barbuy else "utbot.sell"
                active = UTBotDrawObject(
                    tf=self.tf,
                    t_open_ms=latest_bar.t_open_ms,
                    direction=direction,
                    digits=latest_bar.digits,
                    layer="L3",
                    shape="LABEL",
                    points=[
                        Point(
                            t_ms=latest_bar.t_open_ms,
                            price=latest_bar.l if latest_value.barbuy else latest_bar.h,
                        )
                    ],
                    style=Style(token=token),
                    text_key=f"indicator.{token}.active",
                    text_args={
                        "warmup": latest_value.warmup,
                        "confirmed": latest_bar.complete,
                        "direction": direction,
                        "active_signal": True,
                    },
                    state="FRESH",
                    ttl_ms=0,
                    priority=10,
                    z=2,
                    anim=Animation(in_="none", loop=None),
                    source_bars=[len(bars) - 1],
                    confidence=1,
                    reason=f"UT Bot active {'buy' if latest_value.barbuy else 'sell'} state",
                    warmup=latest_value.warmup,
                    confirmed=latest_bar.complete,
                )
                if all(o.id != active.id for o in output):
                    output.append(active)
        return output

    def frame(
        self, kind: Any, snapshot: BarsSnapshot | None = None, bar: Bar | None = None
    ) -> ChartFrame:
        live = max(self.bars.values(), key=lambda b: b.t_open_ms) if self.bars else None
        digits = live.digits if live else self.feed.instrument.digits
        closures = (
            [SessionClosure(**c.model_dump()) for c in self.calendar.closures]
            if self.calendar and kind == "snapshot"
            else []
        )
        fvg = self.fvg_draw_cache.get(self.tf)
        if fvg is None:
            assert self.feed.store
            fvg = FVGDrawing(self.gate.config.zones, Path(self.feed.store.path).with_name(f"worklog-{self.tf}.jsonl"))
            self.fvg_draw_cache[self.tf] = fvg
        fvg_objects = fvg.objects(sorted(self.bars.values(), key=lambda b: b.t_open_ms))
        candidate_objects, candidate_decisions, candidate_worklog, candidate_status = (
            self.candidate_service.snapshot(self.tf) if self.candidate_service else ([], [], [], {}))
        if candidate_status.get("state") == "RUNNING" and self.tf in self.gate.config.candidates.timeframes:
            fvg_objects = []  # The independent EvalPoint owner supplies canonical zones as well.
        structure_marks,structure_state=(self.candidate_service.structure_snapshot(self.tf) if self.candidate_service else ([],None))
        liquidity_pools,liquidity_weekly_open=(self.candidate_service.liquidity_snapshot(self.tf) if self.candidate_service else ([],None))
        call_dry_run=(self.candidate_service.call_dry_run_snapshot(self.tf) if self.candidate_service else None)
        indicator_objects = self._indicator_objects()
        objects = [*indicator_objects, *fvg_objects, *candidate_objects, *structure_marks]
        open_calls = (
            [r.call for r in self.candidate_service.call_ledger.rows if r.call.state in ("PENDING", "ACTIVE")]
            if self.candidate_service
            else []
        )
        if not open_calls and call_dry_run and call_dry_run.stop is not None and call_dry_run.tp1 is not None:
            watch_end = self.now()
            chart_bars = sorted(self.bars.values(), key=lambda b: b.t_open_ms)
            watch_source_bars = [max(0, len(chart_bars) - 1)]
            objects.append(
                DrawObject(
                    layer="L2",
                    shape="ZONE",
                    points=[
                        Point(t_ms=watch_end - timeframe_ms(self.tf), price=call_dry_run.zone_lo),
                        Point(t_ms=watch_end, price=call_dry_run.zone_hi),
                    ],
                    style=Style(token="call.trade"),
                    text_key=f"watch.{call_dry_run.zone_id}",
                    text_args=dict(
                        call_id=f"watch:{call_dry_run.zone_id}",
                        call_state="WATCH",
                        watch_passes=call_dry_run.passes,
                        first_fail=call_dry_run.first_fail,
                        min_r=call_dry_run.min_r,
                        tp1_name=call_dry_run.tp1_name,
                        direction="BULLISH" if call_dry_run.direction == "LONG" else "BEARISH",
                        tf=call_dry_run.tf,
                        end_ms=watch_end,
                        entry_lo=call_dry_run.zone_lo,
                        entry_hi=call_dry_run.zone_hi,
                        entry_mid=call_dry_run.entry_ref,
                        stop=call_dry_run.stop,
                        tp1=call_dry_run.tp1,
                        tp2=None,
                        reward_r=call_dry_run.reward_r,
                        entry_distance=call_dry_run.distance_to_zone,
                        bars_remaining=self.gate.config.trade.call_expiry_bars,
                        broadcast_mode=self.gate.config.calls.broadcast,
                        grade=call_dry_run.grade,
                        grade_notes=list(call_dry_run.grade_notes),
                        live_phase="WATCH",
                    ),
                    state="FRESH",
                    ttl_ms=0,
                    priority=10,
                    z=2,
                    anim=Animation(in_="none", loop=None),
                    source_bars=watch_source_bars,
                    confidence=0,
                    reason="Producer dry-run passes if price returns to the zone",
                    digits=digits,
                )
            )
        thesis = build_thesis(
            tf=self.tf,
            price=self.bid or (live.c if live else None),
            structure=structure_state,
            objects=objects,
            pools=liquidity_pools,
            open_calls=open_calls,
            market_closed=self._closed(),
            dry_run=call_dry_run,
        )
        book_stats = compute_history_stats(self.feed.store, self.feed.broker_symbol or self.feed.instrument.symbol)
        book = build_book(
            tf=self.tf,
            bars=sorted(self.bars.values(), key=lambda b: b.t_open_ms),
            thesis=thesis.model_dump(mode="json"),
            objects=objects,
            pools=liquidity_pools,
            stats=book_stats,
            now_ms=self.now(),
        )
        objects = [*objects, *book_draw_objects(book, sorted(self.bars.values(), key=lambda b: b.t_open_ms))]
        return ChartFrame(
            chart_density=self.gate.config.chart.density,
            thesis=thesis.model_dump(mode="json"),
            book=book,
            liquidity_pools=liquidity_pools,
            liquidity_weekly_open=liquidity_weekly_open,
            structure_state=structure_state,
            candidate_decisions=candidate_decisions,
            candidate_worklog=candidate_worklog,
            candidate_status=candidate_status,
            worklog=sorted(fvg.decisions, key=lambda d: (d.at_ms, d.id))[-8:],
            kind=kind,
            snapshot=snapshot,
            update=BarUpdate(tf=self.tf, bar=bar) if bar else None,
            quality=self.quality(),
            now_ms=self.now(),
            next_close_ms=live.t_open_ms + timeframe_ms(self.tf) if live else None,
            bar_duration_ms=timeframe_ms(self.tf),
            closures=closures,
            calendar_detail=self.calendar_detail,
            resolved_symbol=self.feed.broker_symbol,
            refinement_pending=self.refinement_pending,
            quote=Quote(
                symbol="XAUUSD", bid=self.bid, ask=self.ask, t_ms=self.last_tick_ms, source="mt5"
            )
            if self.bid > 0
            else None,
            objects=objects,
            indicator_enabled=self.gate.config.indicators.ut_bot.for_tf(self.tf).enabled,
            switch_ms=self.switch_ms,
            bar_colors=self.indicator_detail.get("bar_colors", []),
            language=self.gate.config.language,
        )

    def poll(self) -> list[ChartFrame]:
        live: Bar | None
        now_mono = time.monotonic()
        if now_mono - self.last_poll < 1 / self.gate.config.data.render_throttle_hz:
            return []
        self.last_poll = now_mono
        assert self.feed.clock and self.feed.instrument and self.feed.store
        tick = (
            self.feed.api.quote()
            if isinstance(self.feed.api, Mt5Gateway)
            else self.feed.api.symbol_info_tick(self.feed.broker_symbol)
        )
        if tick is None:
            return [self.frame("status")]
        if (
            now_mono - self.last_clock_check > 60
            and self.now() - self.feed.clock.utc_ms(int(tick.time_msc))
            < self.gate.config.data.stale_ms
        ):
            previous_version = self.feed.clock.version
            self.feed.refresh_offset()
            self.last_clock_check = now_mono
            if self.feed.clock.version != previous_version:
                return [self.refine(self.feed.clock)]
        if isinstance(self.feed.api, Mt5Gateway):
            rows = [
                {"time_msc": t.time_msc, "bid": t.bid, "ask": t.ask}
                for t in self.feed.api.drain_ticks()
            ]
            self.bid, self.ask = float(tick.bid), float(tick.ask)
            self.last_tick_ms = self.feed.clock.utc_ms(int(tick.time_msc))
            self.spread = (self.ask - self.bid) / self.feed.instrument.point
        else:
            rows = self.feed.api.copy_ticks_from(
                self.feed.broker_symbol,
                datetime.fromtimestamp(self.cursor_ms / 1000, UTC),
                10000,
                self.feed.api.COPY_TICKS_ALL,
            )
        same_seen = 0
        for row in rows if rows is not None else []:
            raw_ms = int(row["time_msc"])
            if raw_ms < self.cursor_ms:
                continue
            if raw_ms == self.cursor_ms:
                same_seen += 1
                if same_seen <= self.cursor_count:
                    continue
            else:
                self.cursor_ms = raw_ms
                self.cursor_count = 0
                same_seen = 1
            self.cursor_count = same_seen
            utc_ms = self.feed.clock.utc_ms(raw_ms)
            if self.candidate_service and not isinstance(self.feed.api, Mt5Gateway):
                self.candidate_service.ingest(raw_ms, float(row["bid"]))
            self.last_tick_ms = utc_ms
            self.bid, self.ask = float(row["bid"]), float(row["ask"])
            self.spread = (float(row["ask"]) - float(row["bid"])) / self.feed.instrument.point
            closed = self.builder.ingest(utc_ms, float(row["bid"]))
            if closed:
                if closed.t_open_ms not in self.reconciled:
                    self.closed_pending[closed.t_open_ms] = closed
        current_minute = self.builder.current
        if (
            current_minute
            and current_minute.t_open_ms not in self.reconciled
            and self.now() >= current_minute.t_open_ms + 60000 + self.gate.config.data.grace_ms
        ):
            self.closed_pending.setdefault(
                current_minute.t_open_ms, current_minute.transition(complete=True)
            )
        frames = []
        for t, built in list(self.closed_pending.items()):
            if self.now() < t + 60000 + self.gate.config.data.grace_ms:
                continue
            if self.now() < self.reconcile_retry.get(t, 0):
                continue
            try:
                broker = self.feed.broker_minute_record(t, refresh=False)
            except EngineError as error:
                if error.fault.code != "BAR_RECONCILIATION_PENDING":
                    raise
                self.reconcile_retry[t] = self.now() + 10000
                self.detail = error.fault.message + f" UTC minute {t}"
                continue
            correction = self.builder.reconcile(built, broker.bar, self.feed.store)
            self.feed.store.put_broker(broker)
            del self.closed_pending[t]
            self.reconcile_retry.pop(t, None)
            self.reconciled.add(t)
            if self.builder.current and self.builder.current.t_open_ms == t:
                self.builder.current = broker.bar
            if self.tf == "M1":
                self.bars[t] = broker.bar
                frames.append(self.frame("correction" if correction else "update", bar=broker.bar))
            elif correction:
                # Refetch the broker's affected HTF candle, never aggregate across broker day boundaries.
                for bar in self._rates(self.tf, 3):
                    if bar.t_open_ms <= t < bar.t_open_ms + timeframe_ms(self.tf):
                        self.bars[bar.t_open_ms] = bar
                        frames.append(self.frame("correction", bar=bar))
        if self.tf == "M1" and self.builder.current:
            live = self.builder.current
            raw_ms = live.t_open_ms + self.feed.server_utc_offset_s * 1000
            self.debug_bars[live.t_open_ms] = DebugBar(
                t_open_ms=live.t_open_ms,
                t_broker_ms=raw_ms,
                offset_s=self.feed.server_utc_offset_s,
                clock_version=self.feed.clock.version,
                clock_confidence=self.feed.clock.confidence_at(raw_ms),
            )
        else:
            step = timeframe_ms(self.tf)
            raw_tick = int(tick.time_msc)
            phase = 4 * 86400000 if self.tf == "W1" else 0
            raw_open = (raw_tick - phase) // step * step + phase
            t_open = self.feed.clock.utc_ms(raw_open)
            old = self.bars.get(t_open)
            if old:
                payload = old.model_dump(exclude={"id", "object_hash"})
                live = Bar.model_validate(
                    payload
                    | {
                        "h": max(old.h, (self.bid or float(tick.bid))),
                        "l": min(old.l, (self.bid or float(tick.bid))),
                        "c": (self.bid or float(tick.bid)),
                        "complete": False,
                    }
                )
            else:
                for t, old in list(self.bars.items()):
                    if not old.complete and t < t_open:
                        self.bars[t] = old.transition(complete=True)
                        frames.append(self.frame("update", bar=self.bars[t]))
                live = Bar(
                    tf=self.tf,
                    t_open_ms=t_open,
                    o=(self.bid or float(tick.bid)),
                    h=(self.bid or float(tick.bid)),
                    l=(self.bid or float(tick.bid)),
                    c=(self.bid or float(tick.bid)),
                    tick_volume=1,
                    source="mt5",
                    complete=False,
                    digits=self.feed.instrument.digits,
                    clock_confidence=self.feed.clock.confidence_at(raw_open),
                )
        if now_mono - self.last_bar_poll >= self.gate.config.data.bar_poll_ms / 1000:
            self.last_bar_poll = now_mono
            minute_corrected = False
            if self.tf != "M1":
                minutes = self._rates("M1", 2)
                if minutes and self.builder.current:
                    broker_minute = minutes[-1]
                    built_minute = self.builder.current
                    if broker_minute.t_open_ms == built_minute.t_open_ms:
                        divergence = max(
                            abs(getattr(built_minute, k) - getattr(broker_minute, k))
                            for k in ("o", "h", "l", "c")
                        )
                        self.builder.checked += 1
                        if divergence > self.feed.instrument.tick_size:
                            minute_corrected = True
                            self.builder.corrections += 1
                            # Selected chart correction carries the repaired parent candle below.
                            self.detail = f"M1 broker correction at UTC {broker_minute.t_open_ms}"
                        payload = broker_minute.model_dump(exclude={"id", "object_hash"})
                        self.builder.current = Bar.model_validate(
                            payload
                            | {
                                "h": max(broker_minute.h, self.bid),
                                "l": min(broker_minute.l, self.bid),
                                "c": self.bid,
                                "complete": False,
                            }
                        )
            current = self._rates(self.tf, 2)
            for broker_bar in current:
                previous = self.bars.get(broker_bar.t_open_ms)
                if (
                    minute_corrected
                    and self.builder.current
                    and broker_bar.t_open_ms
                    <= self.builder.current.t_open_ms
                    < broker_bar.t_open_ms + timeframe_ms(self.tf)
                ):
                    self.bars[broker_bar.t_open_ms] = broker_bar
                    frames.append(self.frame("correction", bar=broker_bar))
                if (
                    previous
                    and max(
                        abs(getattr(previous, k) - getattr(broker_bar, k))
                        for k in ("o", "h", "l", "c")
                    )
                    > self.feed.instrument.tick_size
                ):
                    self.builder.checked += 1
                    self.builder.corrections += 1
                    self.bars[broker_bar.t_open_ms] = broker_bar
                    frames.append(self.frame("correction", bar=broker_bar))
                if live and broker_bar.t_open_ms == live.t_open_ms:
                    # Broker fixes history/extremes; latest bid still drives the close.
                    payload = broker_bar.model_dump(exclude={"id", "object_hash"})
                    live = Bar.model_validate(
                        payload
                        | {
                            "h": max(broker_bar.h, (self.bid or float(tick.bid))),
                            "l": min(broker_bar.l, (self.bid or float(tick.bid))),
                            "c": (self.bid or float(tick.bid)),
                            "complete": False,
                        }
                    )
                    if self.tf == "M1":
                        self.builder.current = live
        if live:
            self.bars[live.t_open_ms] = live
            frames.append(self.frame("update", bar=live))
        else:
            frames.append(self.frame("status"))
        limit = self.gate.config.chart.visible_bars + self.gate.config.chart.lookback
        for t in sorted(self.bars)[:-limit]:
            self.bars.pop(t, None)
            self.debug_bars.pop(t, None)
        self.reconciled = {t for t in self.reconciled if t >= self.now() - 7 * 86400000}
        return frames

    def debug(self) -> ChartDebug:
        return ChartDebug(
            resolved_symbol=self.feed.broker_symbol,
            bars=list(self.debug_bars.values()),
            corrections=self.builder.corrections,
            checked=self.builder.checked,
            last_tick_ms=self.last_tick_ms,
            spread_points=self.spread,
            switch_ms=self.switch_ms,
            gateway=self.feed.api.telemetry() if isinstance(self.feed.api, Mt5Gateway) else {},
            missing_ranges=self.missing_ranges,
            indicator=self.indicator_detail,
            detail=self.detail + " Ã‚Â· " + self.calendar_detail,
        )

    def refine(self, clock: BrokerClock) -> ChartFrame:
        assert self.feed.store
        if self.backfill:
            self.backfill.close()
            self.backfill = None
        self.feed.store.reproject(clock)
        clock.save(Path(self.feed.config.broker_clock_path))
        self.feed.clock = clock
        self.builder.current = None
        self.closed_pending.clear()
        self.reconciled.clear()
        self.calendar = None
        self.calendar_pending = True
        self.calendar_cursor = 0
        self.calendar_bars.clear()
        self.confirmed_ut.clear()
        self.ut_draw_cache.clear()
        self.provisional_ut.clear()
        if isinstance(self.feed.api, Mt5Gateway):
            self.backfill = ChartBackfill(self.gate)
        snapshot = self.subscribe(self.tf)
        return ChartFrame.model_validate(snapshot.model_dump() | {"kind": "clock_refined"})

    def background_step(self) -> ChartFrame | None:
        """Drain completed background metadata only; never wait for bulk terminal calls."""
        if not self.backfill:
            return None
        changed = False
        while not self.backfill.events.empty():
            event = self.backfill.events.get()
            if "refined" in event:
                return self.refine(event["refined"])
            if "calendar" in event:
                self.calendar = event["calendar"]
            if "pending" in event:
                self.calendar_pending = event["pending"]
            if "detail" in event:
                self.calendar_detail = event["detail"]
            if "refinement_pending" in event:
                self.refinement_pending = event["refinement_pending"]
            if event.get("filled_tf") == self.tf:
                return self.subscribe(self.tf)
            changed = True
        return self.frame("status") if changed else None

    def close(self) -> None:
        if self.candidate_service:
            self.candidate_service.close()
        if self.backfill:
            self.backfill.close()

    def set_indicator(self, options: dict[str, Any]) -> ChartFrame:
        override = UTBotOverride.model_validate(options)
        settings = self.gate.config.indicators.ut_bot
        overrides = dict(settings.per_timeframe)
        old = overrides.get(self.tf, UTBotOverride())
        overrides[self.tf] = UTBotOverride.model_validate(
            old.model_dump() | override.model_dump(exclude_none=True)
        )
        updated = settings.model_copy(update={"per_timeframe": overrides})
        self.gate.config = self.gate.config.model_copy(
            update={
                "indicators": self.gate.config.indicators.model_copy(update={"ut_bot": updated})
            }
        )
        self.confirmed_ut = {k: o for k, o in self.confirmed_ut.items() if o.tf != self.tf}
        self.provisional_ut.clear()
        return self.frame("status")


