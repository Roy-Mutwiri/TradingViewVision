"""Private JSON-lines stdin/stdout worker. Credentials are never command arguments."""

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from oracle.analysis.ledger import CallLedger
from oracle.auth.contracts import ConnectProgress, ConnectRequest
from oracle.auth.profiles import ProfileStore
from oracle.config import load_config
from oracle.data.assumed_calendar import assumed_closed
from oracle.data.auth_session import LoginGate
from oracle.data.live_chart import LiveChart
from oracle.data.mt5_gateway import Mt5Gateway
from oracle.data.sessions import session_intervals
from oracle.director.director import Director
from oracle.director.gamechanger import GamechangerTail
from oracle.director.timeline import Timeline
from oracle.models import timeframe_ms
from oracle.ops.speaker_frame import build_frame
from oracle.ops.speaker_sink import SpeakerSink
from oracle.ops.telemetry import configure_logging
from oracle.transport.chart import ChartFrame
from oracle.transport.errors import boundary_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    configure_logging(Path(config.log_path))
    gate = LoginGate(config, args.config.parent, ProfileStore(args.profiles))
    dashboard_started = False
    chart: LiveChart | None = None
    director: Director | None = None
    last_observe_ms = 0
    source = GamechangerTail(
        Path(config.retention.gamechanger_events).resolve()
        if config.retention.gamechanger_events
        else None
    )
    send_lock = threading.Lock()
    quote_stop = threading.Event()

    def retention_director() -> Director:
        nonlocal director
        gate.status()
        if director is None:
            assert gate.feed
            path = Path(config.retention.timeline_dir) / f"stream-{time.time_ns()}.jsonl"
            director = Director(
                Timeline(path),
                config.language,
                ledger=CallLedger(
                    Path(gate.feed.config.store_path).parent / "analysis-calls.jsonl",
                    config.retention.min_call_life_ms,
                ),
                day_boundary=config.sessions.day_boundary,
                reason_strip_seconds=config.narration.reason_strip_seconds,
                max_pending_age_ms=config.trade.max_pending_age_ms,
            )
        return director

    def retention_updates() -> None:
        while not quote_stop.wait(0.2):
            if director is None:
                continue
            now = time.time_ns() // 1000000
            try:
                source.poll(director, now)
                send({"event": "retention", "data": director.view(now).model_dump(mode="json")})
            except (OSError, ValueError):
                # A rotated or unavailable audience log must not interrupt market data.
                continue

    def send(payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False) + "\n"
        with send_lock:
            sys.stdout.write(encoded)
            sys.stdout.flush()

    def quotes() -> None:
        last = 0
        last_candidate_tick: tuple[int, float] | None = None
        next_allowed = 0.0
        interval = 1 / config.data.render_throttle_hz
        while not quote_stop.wait(min(0.025, interval / 4)):
            live = chart
            feed = gate.feed
            if live and live.candidate_service and feed and isinstance(feed.api, Mt5Gateway):
                raw_tick = feed.api.quote()
                if raw_tick is not None:
                    signature = (int(raw_tick.time_msc), float(raw_tick.bid))
                    if signature != last_candidate_tick:
                        live.candidate_service.ingest(*signature)
                        last_candidate_tick = signature
            if time.perf_counter() < next_allowed:
                continue
            feed = gate.feed
            update = feed.tick_quote() if feed else None
            if update is None or update.received_ms == last:
                continue
            last = update.received_ms
            next_allowed = time.perf_counter() + interval
            send({"event": "quote", "data": update.wire()})

    speaker_sink: SpeakerSink | None = None
    if config.speaker.enabled:
        speaker_sink = SpeakerSink(
            Path(config.speaker.sink_dir),
            queue_size=config.speaker.queue_size,
            max_bytes=config.speaker.max_bytes,
            keep_files=config.speaker.keep_files,
        )
        speaker_sink.start()

    def speaker_frames() -> None:
        """Market frames for the LetsTalk speaker (docs/ORACLE_BRIDGE.md).

        Off the analysis path: it only reads snapshot accessors that return copies under the owner's lock, and it
        never calls chart.poll(), which would consume a frame the renderer is owed. Every exception is swallowed
        and counted - if this thread dies, ORACLE carries on and the speaker sees staleness, which it handles by
        refusing to speak market facts at all.
        """
        assert speaker_sink is not None
        interval = 1 / config.speaker.hz
        seq = 0
        while not quote_stop.wait(interval):
            try:
                live = chart
                if live is None or live.candidate_service is None or director is None:
                    continue
                now = time.time_ns() // 1000000
                tf = live.tf
                _marks, structure_state = live.candidate_service.structure_snapshot(tf)
                pools, weekly_open = live.candidate_service.liquidity_snapshot(tf)
                bars = sorted(live.bars.values(), key=lambda b: b.t_open_ms)
                latest = bars[-1] if bars else None
                seq += 1
                speaker_sink.offer(
                    build_frame(
                        seq=seq,
                        now_ms=now,
                        tf=tf,
                        bid=live.bid,
                        ask=live.ask,
                        tick_ms=live.last_tick_ms,
                        quality=live.quality(),
                        next_close_ms=(latest.t_open_ms + timeframe_ms(tf)) if latest else None,
                        bar_duration_ms=timeframe_ms(tf),
                        structure_state=structure_state,
                        pools=pools,
                        weekly_open=weekly_open,
                        retention=director.view(now),
                        intervals=list(session_intervals(now)),
                        market_closed=bool(director.market_closed),
                        next_open_ms=director.next_open_ms,
                        point=float(getattr(getattr(gate.feed, "instrument", None), "point", 0.01) or 0.01),
                    )
                )
            except Exception:  # noqa: BLE001 - the sink must never affect trading
                speaker_sink.stats["errors"] += 1

    quote_thread = threading.Thread(target=quotes, name="oracle-quote-ipc", daemon=True)
    quote_thread.start()
    if speaker_sink is not None:
        threading.Thread(target=speaker_frames, name="oracle-speaker-frames", daemon=True).start()
    retention_thread = threading.Thread(
        target=retention_updates, name="oracle-retention", daemon=True
    )
    retention_thread.start()

    try:
        for line in sys.stdin:
            request_id: int = -1
            command = ""
            try:
                if len(line) > 1000000:
                    line = ""
                    raise ValueError("Request too large")
                payload = json.loads(line)
                line = ""
                request_id = int(payload["id"])
                command = payload["command"]

                def emit(progress: ConnectProgress) -> None:
                    send(
                        {
                            "id": request_id,
                            "event": "progress",
                            "data": progress.model_dump(mode="json", by_alias=True),
                        }
                    )

                result: Any
                if command == "settings":
                    result = gate.settings()
                elif command == "connect":
                    try:
                        request = ConnectRequest.model_validate(payload["request"])
                    finally:
                        if isinstance(payload.get("request"), dict):
                            payload["request"]["password"] = ""
                    try:
                        result = gate.connect(request, emit)
                    finally:
                        del request
                elif command == "connect_profile":
                    profile = payload["profile"]
                    result = gate.connect_profile(
                        int(profile["login"]),
                        str(profile["server"]),
                        str(profile["passwordType"]),
                        emit,
                    )
                elif command == "preflight":
                    result = gate.preflight(
                        symbol_override=payload.get("symbol"),
                        download=bool(payload.get("download", False)),
                    )
                elif command == "enter":
                    result = gate.status()
                elif command == "chart_subscribe":
                    gate.status()
                    chart = chart or LiveChart(gate)
                    if isinstance(gate.api, Mt5Gateway):
                        with gate.api.foreground():
                            result = chart.subscribe(payload["tf"])
                    else:
                        result = chart.subscribe(payload["tf"])
                elif command == "chart_poll":
                    gate.status()
                    result = [frame.wire() for frame in chart.poll()] if chart else []
                elif command == "chart_background":
                    gate.status()
                    result = chart.background_step() if chart else None
                elif command == "chart_indicator":
                    gate.status()
                    if chart is None:
                        raise ValueError("Subscribe to candles before changing indicator settings")
                    result = chart.set_indicator(payload["options"])
                elif command == "chart_debug":
                    gate.status()
                    chart = chart or LiveChart(gate)
                    result = chart.debug()
                elif command == "ui_settings":
                    gate.status()
                    result = {"mode": config.ui.mode, "language": config.language}
                elif command == "retention_state":
                    result = retention_director().view(time.time_ns() // 1000000)
                elif command == "diagnostics":
                    result = gate.diagnostics()
                elif command == "lock":
                    gate.close()
                    result = True
                else:
                    raise ValueError("Unsupported command")
                if chart and command.startswith("chart_"):
                    now = time.time_ns() // 1000000
                    if now - last_observe_ms >= 1000 or command == "chart_subscribe":
                        assert chart.feed.store
                        closed = [b for b in chart.feed.store.latest("M1", 4) if b.complete]
                        selected = sorted(chart.bars.values(), key=lambda b: b.t_open_ms)
                        closed += [b for b in selected[-4:] if b.complete]
                        current_director = retention_director()
                        try:
                            session_closed = (
                                not chart.calendar.is_tradeable(now)
                                if chart.calendar
                                else assumed_closed(now)
                            )
                            opening = (
                                chart.calendar.next_open(now)
                                if session_closed and chart.calendar
                                else None
                            )
                        except ValueError:
                            session_closed, opening = assumed_closed(now), None
                        if (
                            chart.calendar is None
                            and selected
                            and now - chart.last_tick_ms < 5000
                            and selected[-1].t_open_ms + timeframe_ms(chart.tf) > now
                        ):
                            session_closed = False
                        current_director.set_session(session_closed, opening)
                        current_director.observe(selected[-1] if selected else None, closed, now)
                        last_observe_ms = now
                if gate.authorized is not None and not dashboard_started:
                    import uvicorn

                    from oracle.ops.dashboard import create_dashboard

                    app = create_dashboard(
                        config,
                        args.config.parent / "strings",
                        account_provider=lambda: gate.authorized,
                        frame_provider=(lambda: speaker_sink.latest()) if speaker_sink else None,
                    )
                    threading.Thread(
                        target=uvicorn.run,
                        args=(app,),
                        kwargs={
                            "host": config.dashboard.host,
                            "port": config.dashboard.port,
                            "access_log": False,
                            "log_level": "error",
                        },
                        daemon=True,
                    ).start()
                    dashboard_started = True
                data = (
                    result.wire()
                    if isinstance(result, ChartFrame)
                    else (
                        result.model_dump(mode="json", by_alias=True)
                        if hasattr(result, "model_dump")
                        else result
                    )
                )
                send({"id": request_id, "result": data})
            except Exception as exc:
                # ValidationError and SDK errors can include input values: never forward them.
                line = ""
                if not command.startswith(("chart_", "retention_", "ui_")):
                    gate.close()
                send(
                    {
                        "id": request_id,
                        "error": boundary_error(exc, command).wire(),
                    }
                )
    finally:
        quote_stop.set()
        quote_thread.join(timeout=2)
        retention_thread.join(timeout=2)
        if director:
            director.close(time.time_ns() // 1000000)
        if chart:
            chart.close()
        gate.close()
        if isinstance(gate.api, Mt5Gateway):
            gate.api.close()


if __name__ == "__main__":
    main()
