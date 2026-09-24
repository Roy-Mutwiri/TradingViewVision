"""Independent live owner. Raw broker ticks enter a queue; the chart reads snapshots."""

import hashlib
import bisect
import msvcrt
import queue
import threading
import uuid
from collections import Counter
from pathlib import Path
from typing import Literal

from oracle.analysis.call_drawing import call_objects
from oracle.analysis.contracts import Call
from oracle.analysis.ledger import CallLedger
from oracle.analysis.producer import CallDryRun, CallProducer
from oracle.analysis.resolver import CallResolver
from oracle.candidates.contracts import CANDIDATE_SCHEMA_VERSION, Decision
from oracle.candidates.lifecycle import CandidateEngine
from oracle.candidates.run import CandidateRun
from oracle.candidates.sources import LiveBuckets, replay_points
from oracle.config import OracleConfig
from oracle.data.aggregate import aggregate_m1
from oracle.data.assumed_calendar import assumed_closed
from oracle.data.broker_bar import RawBrokerBar
from oracle.data.mt5_feed import MT5Feed
from oracle.indicators.ut_bot import ut_bot
from oracle.models import Bar, DrawObject, Timeframe, content_hash, timeframe_ms
from oracle.smc.liquidity_contracts import Pool
from oracle.smc.structure import (
    StructureCursor,
    StructureState,
)
from oracle.smc.structure_drawing import structure_objects
from oracle.smc.swings import load_swing_config
from oracle.transport.errors import EngineError


class CandidateService:
    def __init__(self, feed: MT5Feed, config: OracleConfig) -> None:
        self.feed, self.config = feed, config
        self.session_id = uuid.uuid4().hex
        self.inputs: queue.SimpleQueue[tuple[int, float] | None] = queue.SimpleQueue()
        self.lock = threading.Lock()
        self.views: dict[Timeframe, tuple[list[DrawObject], list[Decision]]] = {}
        self.structure_views: dict[Timeframe, tuple[list[DrawObject], StructureState]] = {}
        self.current_openings: dict[Timeframe, int] = {}
        self.liquidity_views: dict[Timeframe, tuple[list[Pool], float | None]] = {}
        self.status: dict[str, object] = {"session_id": self.session_id, "state": "STARTING"}
        self.call_evaluated_by_tf: Counter[str] = Counter()
        self.call_evaluated_since_21_by_tf: Counter[str] = Counter()
        self.call_produced_by_tf: Counter[str] = Counter()
        self.call_produced_since_21_by_tf: Counter[str] = Counter()
        self.call_rejections_since_21_by_tf: Counter[tuple[str, str]] = Counter()
        self.call_dry_runs: dict[Timeframe, CallDryRun] = {}
        self.init_skips: dict[str, str] = {}
        self.startup_backfill_counts: dict[str, int] = {}
        self.light_grade_c_seen: dict[str, int] = {}
        ledger_path = Path(feed.config.store_path).parent / "analysis-calls.jsonl"
        self._ledger_lock = None
        if feed.store is None or str(feed.store.path) != ":memory:":
            self._ledger_lock = ledger_path.with_suffix(".writer.lock").open("a+b")
            if self._ledger_lock.tell() == 0:
                self._ledger_lock.write(b"\0")
                self._ledger_lock.flush()
            self._ledger_lock.seek(0)
            try:
                msvcrt.locking(self._ledger_lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                self._ledger_lock.close()
                raise EngineError(
                    "LEDGER_WRITER_ACTIVE",
                    "Another ORACLE engine still owns this account ledger.",
                    {"path": str(ledger_path)},
                ) from exc
        self.call_ledger = CallLedger(ledger_path, config.retention.min_call_life_ms)
        self.call_producer = CallProducer(config.trade, config.calls)
        self.call_producer.used_zones.update(
            row.call.ob_id for row in self.call_ledger.rows if row.call.ob_id
        )
        for row in self.call_ledger.rows:
            self.call_producer.mark_resolution(row.call)
        assert feed.instrument is not None
        self.call_resolver = CallResolver(self.call_ledger, feed.instrument.point)
        self.thread = threading.Thread(target=self._worker, name="oracle-evalpoints", daemon=True)
        self.thread.start()

    def ingest(self, t_broker_ms: int, bid: float) -> None:
        self.inputs.put((t_broker_ms, bid))

    def snapshot(
        self, tf: Timeframe
    ) -> tuple[list[DrawObject], list[Decision], list[Decision], dict[str, object]]:
        with self.lock:
            objects, decisions = self.views.get(tf, ([], []))
            objects = list(objects)
            tick = (
                self.feed.api.symbol_info_tick(self.feed.broker_symbol)
                if hasattr(self, "feed")
                else None
            )
            price = float(tick.bid) if tick else None
            if price is not None and hasattr(self, "call_ledger"):
                objects.extend(
                    call_objects(self.call_ledger.rows, self.current_openings.get(tf, 0), price, self.config.calls.broadcast)
                )
            for overlay in self.config.zones.htf_overlay:
                if timeframe_ms(overlay) <= timeframe_ms(tf):
                    continue
                for obj in self.views.get(overlay, ([], []))[0]:
                    if obj.style.token == "zone.ob":
                        objects.append(
                            obj.transition(
                                text_args=obj.text_args
                                | {
                                    "htf_overlay": True,
                                    "overlay_opacity": 0.5,
                                    "end_ms": obj.text_args.get("end_ms")
                                    if obj.state == "MITIGATED"
                                    else self.current_openings.get(tf, obj.text_args.get("end_ms")),
                                }
                            )
                        )
            # A close may UPDATE and then PROMOTE at the same EvalPoint. Keep the
            # recorded emission order, rather than sorting those actions by name.
            ordered = sorted(
                (
                    (d, index)
                    for _, history in self.views.values()
                    for index, d in enumerate(history)
                ),
                key=lambda row: (row[0].t_broker_ms, row[0].tf, row[0].seq, row[1]),
            )
            worklog = [decision for decision, _ in ordered][-128:]
            status = dict(self.status)
            if tf not in self.views and status.get("state") == "RUNNING":
                status["state"] = "STARTING"
            return list(objects), list(decisions), worklog, status

    def close(self) -> None:
        self.inputs.put(None)
        self.thread.join(timeout=5)
        if self._ledger_lock is not None and not self._ledger_lock.closed:
            self._ledger_lock.seek(0)
            msvcrt.locking(self._ledger_lock.fileno(), msvcrt.LK_UNLCK, 1)
            self._ledger_lock.close()

    def structure_snapshot(self, tf: Timeframe) -> tuple[list[DrawObject], StructureState | None]:
        with self.lock:
            objects, state = self.structure_views.get(tf, ([], None))
            return list(objects), state

    def liquidity_snapshot(self, tf: Timeframe) -> tuple[list[Pool], float | None]:
        with self.lock:
            pools, weekly = self.liquidity_views.get(tf, ([], None))
            return list(pools), weekly

    def call_dry_run_snapshot(self, tf: Timeframe) -> CallDryRun | None:
        with self.lock:
            return self.call_dry_runs.get(tf)

    def _grade_c_lightweight(
        self,
        tf: Timeframe,
        bar: Bar,
        series: list[Bar],
        now_ms: int,
        m15_state: StructureState | None,
        m15_liquidity: object | None,
    ) -> None:
        cfg = self.config.calls.grade_c
        if not cfg.enabled or tf not in cfg.timeframes:
            return
        if self.light_grade_c_seen.get(tf) == bar.t_open_ms:
            return
        self.light_grade_c_seen[tf] = bar.t_open_ms
        self.call_evaluated_by_tf[tf] += 1
        if bar.t_open_ms + timeframe_ms(tf) >= self._last_21_utc_ms(now_ms):
            self.call_evaluated_since_21_by_tf[tf] += 1
        def reject(reason: str) -> None:
            self.call_producer.reject(reason, tf)  # type: ignore[arg-type]
            if bar.t_open_ms + timeframe_ms(tf) >= self._last_21_utc_ms(now_ms):
                self.call_rejections_since_21_by_tf[(tf, reason)] += 1
        if m15_state is None or m15_state.trend not in ("BULLISH", "BEARISH"):
            reject("GRADE_C_NO_M15_BIAS")
            return
        if len(series) < 40:
            reject("GRADE_C_NO_HISTORY")
            return
        values = ut_bot(series, self.config.indicators.ut_bot.for_tf(tf))
        if not values:
            reject("GRADE_C_NO_UT")
            return
        value = values[-1]
        if value.warmup or value.provisional or not (value.buy or value.sell):
            reject("GRADE_C_NO_FLIP")
            return
        direction: Literal["LONG", "SHORT"] = "LONG" if value.buy else "SHORT"
        if (direction == "LONG" and m15_state.trend != "BULLISH") or (direction == "SHORT" and m15_state.trend != "BEARISH"):
            reject("GRADE_C_BIAS_MISMATCH")
            return
        active = [r.call for r in self.call_ledger.rows if r.call.state in ("PENDING", "ACTIVE")]
        if any((c.grade == "C" and c.timeframe == tf and c.state in ("PENDING", "ACTIVE")) for c in active):
            reject("MAX_ACTIVE_PER_DIRECTION")
            return
        leg_id = f"ut:{tf}:{direction}:{m15_state.last_event.id if m15_state.last_event else m15_state.trend_since_ms or 0}"
        if leg_id in self.call_producer.spent_zones:
            reject("SPENT_ZONE")
            return
        atr = value.atr
        stop_line = value.stop
        if atr is None or stop_line is None or atr <= 0:
            reject("GRADE_C_NO_ATR")
            return
        tick = self.feed.api.symbol_info_tick(self.feed.broker_symbol)
        spread = max(0.0, float(getattr(tick, "ask", bar.c)) - float(getattr(tick, "bid", bar.c))) if tick else 0.0
        entry = bar.c + spread if direction == "LONG" else bar.c
        stop = stop_line - cfg.stop_buffer_atr * atr if direction == "LONG" else stop_line + cfg.stop_buffer_atr * atr
        risk = abs(entry - stop)
        if risk < self.config.trade.min_stop_points:
            reject("STOP_MIN")
            return
        if risk > self.config.trade.max_stop_atr * atr:
            reject("STOP_BEYOND_MAX_ATR")
            return
        pools: list[Pool] = []
        if m15_liquidity is not None:
            if direction == "LONG":
                pools = list(m15_liquidity.pools_above(entry, tf))  # type: ignore[attr-defined]
            else:
                pools = list(m15_liquidity.pools_below(entry, tf))  # type: ignore[attr-defined]
        target_pool = pools[0] if pools else None
        if target_pool:
            target = target_pool.level
        else:
            target = entry + cfg.fallback_r * risk if direction == "LONG" else entry - cfg.fallback_r * risk
        reward_r = abs(target - entry) / risk
        if reward_r < cfg.min_r:
            reject("R_BELOW_MIN")
            return
        created = bar.t_open_ms + timeframe_ms(tf)
        expires = created + self.config.trade.call_expiry_bars * timeframe_ms(tf)
        try:
            call = Call(
                id="",
                created_ms=created,
                kind="STRUCTURE",
                direction=direction,
                entry_lo=entry,
                entry_hi=entry,
                entry_ref=entry,
                trigger_price=None,
                invalidation=stop,
                target=target,
                expires_ms=expires,
                state_hash=content_hash({"tf": tf, "bar": bar.t_open_ms, "grade": "C", "trend": m15_state.trend})[:16],
                reason=f"UT Bot flip ? {tf} scalp ? M15 {m15_state.trend.lower()} bias",
                reason_chain=("UT Bot flip", f"M15 {m15_state.trend.lower()} bias", "Grade C scalp"),
                symbol="XAUUSD",
                clock_version=self.feed.clock.version if self.feed.clock else 1,
                state="PENDING",
                eval_from_ms=created,
                eval_to_ms=expires,
                day_boundary=self.config.sessions.day_boundary,
                created_trading_day="",
                resolved_trading_day=None,
                timeframe=tf,
                tp2=None,
                in_ote=False,
                ob_id=leg_id,
                structure_event_id=m15_state.last_event.id if m15_state.last_event else None,
                target_pool_id=target_pool.id if target_pool else None,
                source_bars=(len(series) - 1,),
                grade="C",
                grade_notes=("scalp", f"with M15 {m15_state.trend.lower()} bias"),
            )
        except ValueError:
            reject("CALL_GEOMETRY_INVALID")
            return
        if any(
            row.call.grade == "C"
            and row.call.timeframe == tf
            and row.call.created_ms == created
            and row.call.direction == direction
            for row in self.call_ledger.rows
        ):
            return
        before = len(self.call_ledger.rows)
        try:
            self.call_ledger.create(call)
        except ValueError:
            return
        if len(self.call_ledger.rows) > before:
            self.call_produced_by_tf[tf] += 1
            if created >= self._last_21_utc_ms(now_ms):
                self.call_produced_since_21_by_tf[tf] += 1

    def _grade_c_call(
        self,
        run: CandidateRun,
        bar: Bar,
        minutes: list[Bar],
        now_ms: int,
        m15_state: StructureState | None,
    ) -> None:
        cfg = self.config.calls.grade_c
        if not cfg.enabled or bar.tf not in cfg.timeframes:
            return
        if m15_state is None or m15_state.trend not in ("BULLISH", "BEARISH"):
            self.call_producer.reject("GRADE_C_NO_M15_BIAS", bar.tf)  # type: ignore[arg-type]
            return
        settings = self.config.indicators.ut_bot.for_tf(bar.tf)
        series = sorted(run.engine.closed, key=lambda item: item.t_open_ms)
        values = ut_bot(series, settings.key, settings.atr_period, settings.heikin_ashi, True)
        if not values or values[-1].warmup or not values[-1].confirmed:
            return
        flip = values[-1]
        if not (flip.buy or flip.sell):
            return
        direction: Literal["LONG", "SHORT"] = "LONG" if flip.buy else "SHORT"
        expected = "LONG" if m15_state.trend == "BULLISH" else "SHORT"
        if direction != expected:
            self.call_producer.reject("GRADE_C_BIAS_MISMATCH", bar.tf)  # type: ignore[arg-type]
            return
        active = [r.call for r in self.call_ledger.rows if r.call.state in ("PENDING", "ACTIVE")]
        if any(c.grade == "C" and c.timeframe == bar.tf for c in active):
            self.call_producer.reject("CONCURRENT_SAME_TF", bar.tf)
            return
        leg_id = f"ut:{bar.tf}:{direction}:{m15_state.last_event.id if m15_state.last_event else m15_state.trend_since_ms or 0}"
        if leg_id in self.call_producer.spent_zones:
            self.call_producer.reject("ZONE_SPENT", bar.tf)
            return
        atr = run.engine.atr.value or flip.atr
        if atr is None or flip.stop is None:
            return
        tick = self.feed.api.symbol_info_tick(self.feed.broker_symbol)
        spread = max(0.0, float(tick.ask - tick.bid)) if tick else 0.0
        entry = bar.c + spread if direction == "LONG" else bar.c
        stop = (flip.stop - cfg.stop_buffer_atr * atr) if direction == "LONG" else (flip.stop + cfg.stop_buffer_atr * atr)
        local_state = run.engine.ob.structure.state if run.engine.ob and run.engine.ob.structure else None
        if local_state:
            if direction == "LONG" and local_state.protected_low is not None:
                stop = min(stop, local_state.protected_low - cfg.stop_buffer_atr * atr)
            if direction == "SHORT" and local_state.protected_high is not None:
                stop = max(stop, local_state.protected_high + cfg.stop_buffer_atr * atr)
        risk = abs(entry - stop)
        if risk < self.config.trade.min_stop_points:
            self.call_producer.reject("STOP_TOO_TIGHT", bar.tf)
            return
        if risk > self.config.trade.max_stop_atr * atr:
            self.call_producer.reject("STOP_TOO_WIDE", bar.tf)
            return
        liq = run.engine.liquidity
        pools = (liq.pools_above(entry, bar.tf) if direction == "LONG" else liq.pools_below(entry, bar.tf)) if liq else []
        target_pool = pools[0] if pools else None
        fallback = entry + cfg.fallback_r * risk if direction == "LONG" else entry - cfg.fallback_r * risk
        target = target_pool.level if target_pool is not None else fallback
        reward_r = abs(target - entry) / max(0.000001, risk)
        if reward_r < cfg.min_r:
            self.call_producer.reject("R_BELOW_MIN", bar.tf)
            return
        if direction == "LONG" and not (stop < entry < target):
            self.call_producer.reject("CALL_GEOMETRY_INVALID", bar.tf)  # type: ignore[arg-type]
            return
        if direction == "SHORT" and not (target < entry < stop):
            self.call_producer.reject("CALL_GEOMETRY_INVALID", bar.tf)  # type: ignore[arg-type]
            return
        created = bar.t_open_ms + timeframe_ms(bar.tf)
        call = Call(
            created_ms=created,
            kind="STRUCTURE",
            direction=direction,
            entry_lo=entry,
            entry_hi=entry,
            entry_ref=entry,
            invalidation=stop,
            target=target,
            expires_ms=created + self.config.trade.call_expiry_bars * timeframe_ms(bar.tf),
            state_hash=content_hash((bar.id, "GRADE_C", m15_state.trend, leg_id)),
            reason=f"UT Bot flip with M15 {m15_state.trend.lower()} bias",
            reason_chain=(
                f"{bar.tf} UT Bot {'buy' if direction == 'LONG' else 'sell'} flip",
                f"M15 {m15_state.trend.lower()} bias",
                f"TP1 {target_pool.geometry.name if target_pool else '1.5R'}",
            ),
            grade="C",
            grade_notes=("scalp", f"with M15 {m15_state.trend.lower()} bias"),
            symbol=bar.symbol,
            clock_version=self.feed.clock.version if self.feed.clock else 1,
            timeframe=bar.tf,
            tp2=None,
            in_ote=None,
            ob_id=leg_id,
            structure_event_id=m15_state.last_event.id if m15_state.last_event else None,
            target_pool_id=target_pool.id if target_pool else None,
            source_bars=(len(series) - 1,),
        )
        before = len(self.call_ledger.rows)
        self.call_ledger.create(call)
        if len(self.call_ledger.rows) > before:
            self.call_produced_by_tf[bar.tf] += 1
            if created >= self._last_21_utc_ms(now_ms):
                self.call_produced_since_21_by_tf[bar.tf] += 1

    def _native(self, tf: Timeframe, observed_ms: int) -> list[Bar]:
        assert self.feed.clock
        rows = self.feed.api.copy_rates_from_pos(
            self.feed.broker_symbol, getattr(self.feed.api, f"TIMEFRAME_{tf}"), 0, 4
        )
        result: list[Bar] = []
        for row in rows if rows is not None else []:
            raw = self.feed._row(row, int(row["time"]) * 1000 + timeframe_ms(tf) <= observed_ms)
            raw = RawBrokerBar.model_validate(raw.model_dump() | {"tf": tf})
            result.append(raw.normalize(self.feed.clock).bar)
        return result

    def _worker(self) -> None:
        assert self.feed.store and self.feed.clock
        store = self.feed.store.fork()
        runs: dict[Timeframe, CandidateRun] = {}
        buckets: dict[Timeframe, LiveBuckets] = {}
        openings: dict[Timeframe, int] = {}
        indices: dict[Timeframe, int] = {}
        display_bars: dict[Timeframe, Bar] = {}
        light_closes: dict[Timeframe, int] = {}
        structures: dict[Timeframe, StructureCursor | None] = {}
        swing_config = load_swing_config(Path("config/weights.yaml"))
        root = Path(self.feed.config.store_path).parent / "runs" / self.session_id
        minute_bucket = -1
        recent_minutes: list[Bar] = []
        try:
            minute_history = [
                b for b in store.latest("M1", 110000) if b.complete and b.source == "mt5"
            ]
            minute_by_time = {b.t_open_ms: b for b in minute_history}
            minute_times = sorted(minute_by_time)
            tf_priority = {"M15": 0, "M5": 1, "M1": 2, "M30": 3, "H1": 4, "H4": 5, "D1": 6, "W1": 7}
            while True:
                tick = self.inputs.get()
                if tick is None:
                    break
                broker_ms, bid = tick
                utc_ms = self.feed.clock.utc_ms(broker_ms)
                offset_s = (broker_ms - utc_ms) // 1000
                if utc_ms // 60000 != minute_bucket:
                    recent_minutes = [
                        b for b in store.latest("M1", 300) if b.complete and b.source == "mt5"
                    ]
                    minute_bucket = utc_ms // 60000
                    m15_cursor = structures.get("M15")
                    m15_run = runs.get("M15")
                    m15_liq = m15_run.engine.liquidity if m15_run else None
                    if recent_minutes:
                        m1_bar = recent_minutes[-1]
                        if light_closes.get("M1") != m1_bar.t_open_ms:
                            light_closes["M1"] = m1_bar.t_open_ms
                            self._grade_c_lightweight("M1", m1_bar, recent_minutes[-220:], utc_ms, m15_cursor.state if m15_cursor else None, m15_liq)
                        m5_bars = aggregate_m1(store, self.feed.clock, "M5", 80, utc_ms)
                        if m5_bars:
                            m5_bar = m5_bars[-1]
                            if light_closes.get("M5") != m5_bar.t_open_ms:
                                light_closes["M5"] = m5_bar.t_open_ms
                                self._grade_c_lightweight("M5", m5_bar, m5_bars[-80:], utc_ms, m15_cursor.state if m15_cursor else None, m15_liq)
                for tf in sorted(
                    self.config.candidates.timeframes,
                    key=lambda value: tf_priority.get(value, 99),
                ):
                    duration = timeframe_ms(tf)
                    opening = self.feed.clock.utc_ms(broker_ms // duration * duration)
                    if tf not in runs:
                        replay_start = self._last_21_utc_ms(utc_ms)
                        if tf == "M1":
                            history = [
                                b
                                for b in minute_history
                                if b.complete and b.source == "mt5" and b.t_open_ms + duration <= opening
                            ][-2200:]
                        else:
                            history = [
                                b
                                for b in aggregate_m1(store, self.feed.clock, tf, 4000, opening)
                                if b.complete and b.t_open_ms + duration <= opening
                            ]
                        seed_map = {
                            b.t_open_ms: b
                            for b in history
                            if b.t_open_ms < replay_start
                        }
                        for b in self._native(tf, broker_ms):
                            if b.complete and b.t_open_ms + duration <= opening and b.t_open_ms < replay_start:
                                seed_map[b.t_open_ms] = b
                        seed = sorted(seed_map.values(), key=lambda b: b.t_open_ms)
                        if tf != "M15":
                            seed_caps = {"M1": 720, "M5": 720, "M30": 480, "H1": 360, "H4": 240, "D1": 180, "W1": 120}
                            seed = seed[-seed_caps.get(tf, 480):]
                        if len(seed) < 14:
                            self.init_skips[tf] = f"seed_lt_14:{len(seed)}"
                            continue
                        backfill = [
                            b
                            for b in history
                            if replay_start <= b.t_open_ms and b.t_open_ms + duration <= opening
                        ]
                        # Startup must not leave the broadcast waiting while every notebook
                        # timeframe replays a full day. M15 remains the audit/display stream;
                        # the other live producer streams seed from history and then replay only
                        # a bounded tail before taking real closes. Replay/backtest goldens still
                        # use the offline harness, not this startup fast path.
                        if tf != "M15":
                            backfill_caps = {"M1": 90, "M5": 48, "M30": 16, "H1": 12, "H4": 8, "D1": 4, "W1": 4}
                            backfill = backfill[-backfill_caps.get(tf, 24):]
                        self.init_skips.pop(tf, None)
                        self.startup_backfill_counts[tf] = len(backfill)
                        directory = root if tf == "M15" else root / tf
                        # Each configured timeframe is a separate run stream (one point/bucket).
                        # M15 is the root audit stream used by the broadcast capture.
                        engine = CandidateEngine(
                            tf,
                            seed,
                            self.config.zones,
                            ttl_bars=self.config.candidates.candidate_ttl_bars,
                            offset_s=offset_s,
                            initial_partial_bar=broker_ms // 250
                            != (broker_ms // duration * duration) // 250,
                            order_blocks_enabled=True,
                            structure_config=self.config.structure,
                            swing_config=swing_config,
                            liquidity_enabled=True,
                            liquidity_config=self.config.liquidity,
                            sessions_config=self.config.sessions,
                            seed_minutes=[
                                b for b in minute_history if b.t_open_ms + 60000 <= opening
                            ],
                        )
                        structures[tf] = (
                            engine.ob.structure if engine.ob else engine.liquidity_structure
                        )
                        # Other TF streams may have created the parent directory already.
                        if tf == "M15" and directory.exists():
                            directory = root / "M15"
                        runs[tf] = CandidateRun(
                            engine,
                            directory,
                            dict(
                                schema_version=CANDIDATE_SCHEMA_VERSION,
                                ob_schema_version=1,
                                order_blocks_enabled=True,
                                liquidity_enabled=True,
                                liquidity_schema_version=1,
                                structure_schema_version=2,
                                liquidity_config=self.config.liquidity.model_dump(mode="json"),
                                sessions_config=self.config.sessions.model_dump(mode="json"),
                                structure_config=self.config.structure.model_dump(mode="json"),
                                swing_config=swing_config.model_dump(mode="json"),
                                fvg_schema_version=3,
                                fvg_record_schema_version=4,
                                initial_partial_bar=engine.initial_partial_bar,
                                initial_missing_prefix=dict(start_ms=opening, end_ms=utc_ms)
                                if engine.initial_partial_bar
                                else None,
                                tf=tf,
                                broker=self.config.data.canonical_broker,
                                server=self.feed.api.account_info().server,
                                symbol=self.feed.broker_symbol,
                                clock_version=self.feed.clock.version,
                                offset_s=offset_s,
                                bucket_ms=self.config.eval.live_bucket_ms,
                                zones=self.config.zones.model_dump(mode="json"),
                                weights_hash=hashlib.sha256(
                                    Path("config/weights.yaml").read_bytes()
                                ).hexdigest(),
                                candidate_ttl_bars=self.config.candidates.candidate_ttl_bars,
                                seed_sha256=hashlib.sha256(
                                    "".join(b.canonical_json() + "\n" for b in seed).encode()
                                ).hexdigest(),
                            ),
                            record_points=self.config.eval.record_evalpoints,
                        )
                        buckets[tf] = LiveBuckets(self.config.eval.live_bucket_ms)
                        cursor = structures[tf]
                        (directory / "structure-events.jsonl").write_text(
                            "".join(e.canonical_json() + "\n" for e in cursor.events)
                            if cursor
                            else "",
                            encoding="utf-8",
                        )
                        openings[tf], indices[tf] = opening, 0
                        if backfill:
                            for point in replay_points(backfill, minute_history)[0]:
                                closed = backfill[point.bar_index]
                                closed_minutes = []
                                call_minutes = minute_history
                                if engine.liquidity:
                                    lo = bisect.bisect_right(
                                        minute_times, engine.liquidity.calendar.last_ms
                                    )
                                    hi = bisect.bisect_right(minute_times, point.t_broker_ms - 60000)
                                    closed_minutes = [minute_by_time[t] for t in minute_times[lo:hi]]
                                    call_lo = bisect.bisect_left(
                                        minute_times, point.t_broker_ms - 3 * 86_400_000
                                    )
                                    call_minutes = [minute_by_time[t] for t in minute_times[call_lo:hi]]
                                run = runs[tf]
                                run.process(
                                    point,
                                    parent_open_ms=closed.t_open_ms,
                                    closed_bar=closed if point.bar_phase == "CLOSE" else None,
                                    closed_minutes=closed_minutes,
                                )
                                if point.bar_phase == "CLOSE":
                                    m15_cursor = structures.get("M15")
                                    self._calls(
                                        run,
                                        closed,
                                        call_minutes,
                                        point.t_broker_ms,
                                        m15_cursor.state if m15_cursor else None,
                                    )
                                    indices[tf] = point.bar_index + 1
                            cursor = engine.ob.structure if engine.ob else engine.liquidity_structure
                            structures[tf] = cursor
                    run, bucket = runs[tf], buckets[tf]
                    if opening != openings[tf]:
                        native = self._native(tf, broker_ms)
                        closed = next(
                            (b for b in native if b.t_open_ms == openings[tf] and b.complete), None
                        )
                        if closed is None:
                            # Genuine missing authoritative close, never silently confirmed.
                            last_price = run.engine.forming.c if run.engine.forming else bid
                            for point in bucket.close(
                                openings[tf] + duration + offset_s * 1000, last_price, indices[tf]
                            ):
                                run.process(point, parent_open_ms=openings[tf], data_gap=True)
                        else:
                            for point in bucket.close(
                                openings[tf] + duration + offset_s * 1000, closed.c, indices[tf]
                            ):
                                run.process(
                                    point,
                                    parent_open_ms=openings[tf],
                                    closed_bar=closed if point.bar_phase == "CLOSE" else None,
                                    closed_minutes=[
                                        b
                                        for b in recent_minutes
                                        if b.t_open_ms > run.engine.liquidity.calendar.last_ms
                                        and b.t_open_ms + 60000
                                        <= point.t_broker_ms - offset_s * 1000
                                    ]
                                    if run.engine.liquidity
                                    else [],
                                )
                                if point.bar_phase == "CLOSE":
                                    prior = structures[tf]
                                    updated = (
                                        run.engine.ob.structure
                                        if run.engine.ob
                                        else run.engine.liquidity_structure
                                    )
                                    structures[tf] = updated
                                    if updated and len(updated.events) > (
                                        len(prior.events) if prior else 0
                                    ):
                                        with (run.directory / "structure-events.jsonl").open(
                                            "a", encoding="utf-8"
                                        ) as file:
                                            file.write(updated.events[-1].canonical_json() + "\n")
                                    minute_view = {m.t_open_ms: m for m in minute_history}
                                    minute_view.update({m.t_open_ms: m for m in recent_minutes})
                                    m15_cursor = structures.get("M15")
                                    self._calls(
                                        run,
                                        closed,
                                        list(minute_view.values()),
                                        utc_ms,
                                        m15_cursor.state if m15_cursor else None,
                                    )
                        openings[tf] = opening
                        indices[tf] += 1
                    for point in bucket.ingest(broker_ms, bid, indices[tf]):
                        run.process(
                            point,
                            parent_open_ms=openings[tf],
                            closed_minutes=[
                                b
                                for b in recent_minutes
                                if b.t_open_ms > run.engine.liquidity.calendar.last_ms
                                and b.t_open_ms + 60000 <= point.t_broker_ms - offset_s * 1000
                            ]
                            if run.engine.liquidity
                            else [],
                        )
                    previous_display = display_bars.get(tf)
                    if previous_display is None or previous_display.t_open_ms != opening:
                        display_bars[tf] = Bar(
                            tf=tf,
                            t_open_ms=opening,
                            o=bid,
                            h=bid,
                            l=bid,
                            c=bid,
                            tick_volume=1,
                            source="mt5",
                            complete=False,
                            digits=run.engine.closed[-1].digits,
                        )
                    else:
                        display_bars[tf] = Bar.model_validate(
                            previous_display.model_dump()
                            | dict(
                                h=max(previous_display.h, bid),
                                l=min(previous_display.l, bid),
                                c=bid,
                                id="",
                                object_hash="",
                            )
                        )
                    with self.lock:
                        self.current_openings[tf] = opening
                        liq = run.engine.liquidity
                        if liq:
                            from oracle.data.analytical_days import trading_week_bounds

                            week_start, _ = trading_week_bounds(
                                utc_ms, self.config.sessions.day_boundary
                            )
                            weekly = liq.calendar.weeks.get(week_start)
                            ids = set(liq.named.values()) | {
                                oid
                                for oid in liq.active
                                if liq.pools[oid].state in ("FRESH", "TOUCHED")
                            }
                            self.liquidity_views[tf] = (
                                [
                                    liq.pools[oid]
                                    for oid in sorted(
                                        ids, key=lambda oid: (oid not in liq.named.values(), oid)
                                    )
                                ],
                                weekly[2].o if weekly else None,
                            )
                        cursor = structures[tf]
                        if cursor:
                            self.structure_views[tf] = (
                                structure_objects(cursor, opening),
                                cursor.state,
                            )
                        self.views[tf] = (
                            run.drawings(openings[tf], display_bar=display_bars[tf]),
                            run.engine.decisions[-128:],
                        )
                        self.status = dict(
                            session_id=self.session_id,
                            state="RUNNING",
                            run_path=str(runs.get("M15", run).directory.resolve()),
                            configured_timeframes=list(self.config.candidates.timeframes),
                            totals=dict(
                                Counter(
                                    d.reason or d.action
                                    for r in runs.values()
                                    for d in r.engine.decisions
                                )
                            ),
                            ob_rejection_criteria=dict(
                                Counter(
                                    str(d.get("criterion", d.get("reason")))
                                    for r in runs.values()
                                    for d in (r.engine.ob.rejections if r.engine.ob else [])
                                )
                            ),
                            ob_seed_rejection_criteria=dict(
                                Counter(
                                    str(d.get("criterion", d.get("reason")))
                                    for r in runs.values()
                                    for d in r.engine.ob_seed_rejections
                                )
                            ),
                            call_rejections=dict(self.call_producer.rejections),
                            call_diagnostics=self._call_diagnostics(utc_ms),
                            active_timeframes=sorted(runs.keys(), key=lambda value: tf_priority.get(value, 99)),
                            init_skips=dict(self.init_skips),
                            startup_backfill_counts=dict(self.startup_backfill_counts),
                            calls=len(self.call_ledger.rows),
                        )
        except Exception as error:
            with self.lock:
                self.status.update(state="FAILED", error=f"{type(error).__name__}: {error}")
        finally:
            store.close()

    def _last_21_utc_ms(self, now_ms: int) -> int:
        day = now_ms // 86_400_000 * 86_400_000
        boundary = day + 21 * 3_600_000
        return boundary if now_ms >= boundary else boundary - 86_400_000

    def _call_diagnostics(self, now_ms: int) -> dict[str, object]:
        tfs = list(self.config.candidates.timeframes)
        boundary = self._last_21_utc_ms(now_ms)
        rejections = {
            tf: {reason: count for (rtf, reason), count in self.call_producer.rejections_by_tf.items() if rtf == tf}
            for tf in tfs
        }
        rejections_since = {
            tf: {reason: count for (rtf, reason), count in self.call_rejections_since_21_by_tf.items() if rtf == tf}
            for tf in tfs
        }
        ledger_since: dict[str, dict[str, int]] = {tf: {} for tf in tfs}
        for row in self.call_ledger.rows:
            call = row.call
            tf = call.timeframe or "M15"
            if tf not in ledger_since or call.created_ms < boundary:
                continue
            grade = call.grade or "A"
            ledger_since[tf][grade] = ledger_since[tf].get(grade, 0) + 1
        return {
            "source_marker": "workspace_candidate_service_always_on_v2",
            "since_21_utc_ms": boundary,
            "evaluated": {tf: self.call_evaluated_by_tf.get(tf, 0) for tf in tfs},
            "evaluated_since_21utc": {tf: self.call_evaluated_since_21_by_tf.get(tf, 0) for tf in tfs},
            "produced": {tf: self.call_produced_by_tf.get(tf, 0) for tf in tfs},
            "produced_since_21utc": {tf: self.call_produced_since_21_by_tf.get(tf, 0) for tf in tfs},
            "ledger_created_since_21utc_by_tf_grade": ledger_since,
            "rejections": rejections,
            "rejections_since_21utc": rejections_since,
        }

    def _cancel_stale_pending_calls(self, evaluation_ms: int, price: float) -> None:
        for row in self.call_ledger.rows:
            current_call = row.call
            if current_call.state != "PENDING":
                continue
            pending_age_ms = evaluation_ms - current_call.created_ms
            too_old = pending_age_ms >= self.config.trade.max_pending_age_ms
            too_far = (
                abs(current_call.effective_entry_ref - price)
                > self.config.trade.max_live_pending_distance_points
            )
            if too_old or too_far:
                self.call_ledger.cancel(
                    current_call.id,
                    "SUPERSEDED_BY_NEW_ANALYSIS",
                    at_ms=evaluation_ms,
                )

    def _calls(
        self,
        run: CandidateRun,
        bar: Bar,
        minutes: list[Bar],
        now_ms: int,
        m15_state: StructureState | None = None,
    ) -> None:
        engine, ob, liq = run.engine, run.engine.ob, run.engine.liquidity
        evaluation_ms = bar.t_open_ms + timeframe_ms(bar.tf)
        self.call_evaluated_by_tf[bar.tf] += 1
        if evaluation_ms >= self._last_21_utc_ms(now_ms):
            self.call_evaluated_since_21_by_tf[bar.tf] += 1
        self._cancel_stale_pending_calls(evaluation_ms, bar.c)
        if not ob or not liq or not ob.structure or engine.atr.value is None:
            self.call_producer.reject("NO_STRUCTURE_EVENT", bar.tf)
            if evaluation_ms >= self._last_21_utc_ms(now_ms):
                self.call_rejections_since_21_by_tf[(bar.tf, "NO_STRUCTURE_EVENT")] += 1
            self._grade_c_call(run, bar, minutes, now_ms, m15_state)
            return
        rows = self.call_ledger.rows
        for row in rows:
            current_call = row.call
            if current_call.state not in ("PENDING", "ACTIVE"):
                self.call_producer.mark_resolution(current_call)
                continue
            relevant = [
                m
                for m in minutes
                if current_call.eval_from_ms <= m.t_open_ms < current_call.eval_to_ms
            ]
            self.call_resolver.evaluate(
                current_call.id,
                relevant,
                now_ms,
                clock_version=current_call.clock_version,
                is_tradeable=lambda t: not assumed_closed(t),
                coverage_through_ms=max(
                    (m.t_open_ms + 60000 for m in relevant), default=current_call.eval_from_ms
                ),
                can_activate=lambda call: self.call_producer.can_activate(
                    call, [item.call for item in self.call_ledger.rows]
                ),
            )
        active = [r.call for r in self.call_ledger.rows if r.call.state in ("PENDING", "ACTIVE")]
        considered_record = False
        dry_runs: list[CallDryRun] = []
        for record in sorted(ob.records, key=lambda r: (r.geometry.created_ms, r.id)):
            if record.state not in ("FRESH", "TOUCHED", "MITIGATED"):
                continue
            considered_record = True
            event = next(
                (e for e in ob.structure.events if e.id == record.validated_by_event_id), None
            )
            if event is None:
                continue
            evidence_state = ob.structure.state.model_copy(update={"last_event": event})
            direction: Literal["LONG", "SHORT"] = (
                "LONG" if record.geometry.direction == "BULLISH" else "SHORT"
            )
            dry_runs.append(
                self.call_producer.dry_run(
                    ob=record,
                    fvgs=list(engine.cursor.records),
                    structure=evidence_state,
                    liquidity=liq,
                    bar=bar,
                    atr=engine.atr.value,
                    active=active,
                )
            )
            active, cancelled = self.call_producer.htf_arbitration(
                active, direction, record.geometry.tf
            )
            for call_id in cancelled:
                self.call_ledger.cancel(
                    call_id,
                    "SUPERSEDED_BY_NEW_ANALYSIS",
                    at_ms=bar.t_open_ms + timeframe_ms(bar.tf),
                )
            assert self.feed.clock is not None
            before_rejections = Counter(self.call_producer.rejections_by_tf)
            produced = self.call_producer.construct(
                ob=record,
                fvgs=list(engine.cursor.records),
                structure=evidence_state,
                liquidity=liq,
                bar=bar,
                atr=engine.atr.value,
                clock_version=self.feed.clock.version,
                active=active,
            )
            after_rejections = Counter(self.call_producer.rejections_by_tf)
            if bar.t_open_ms + timeframe_ms(bar.tf) >= self._last_21_utc_ms(now_ms):
                for key, count in (after_rejections - before_rejections).items():
                    self.call_rejections_since_21_by_tf[key] += count
            if produced:
                self.call_ledger.create(produced)
                self.call_produced_by_tf[produced.timeframe or record.geometry.tf] += 1
                if produced.created_ms >= self._last_21_utc_ms(now_ms):
                    self.call_produced_since_21_by_tf[produced.timeframe or record.geometry.tf] += 1
                active.append(produced)
        with self.lock:
            if dry_runs:
                self.call_dry_runs[bar.tf] = sorted(
                    dry_runs,
                    key=lambda item: (not item.passes, item.distance_to_zone, item.first_fail or ""),
                )[0]
            else:
                self.call_dry_runs.pop(bar.tf, None)
        if not considered_record:
            self.call_producer.reject("NO_STRUCTURE_EVENT", bar.tf)
            if bar.t_open_ms + timeframe_ms(bar.tf) >= self._last_21_utc_ms(now_ms):
                self.call_rejections_since_21_by_tf[(bar.tf, "NO_STRUCTURE_EVENT")] += 1
        self._grade_c_call(run, bar, minutes, now_ms, m15_state)
