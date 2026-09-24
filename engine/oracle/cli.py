"""Phase-gated operator command line."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from oracle.config import load_config
from oracle.ops.dashboard import create_dashboard
from oracle.ops.telemetry import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/oracle.yaml"))
    parser.add_argument(
        "command",
        choices=["dashboard", "check-config", "replay-proof", "clock-derive", "clock-proof"],
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--calendar", type=Path)
    parser.add_argument("--start-ms", type=int)
    parser.add_argument("--end-ms", type=int)
    parser.add_argument("--year", type=int, default=datetime.now(UTC).year - 1)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "check-config":
        print(config.canonical_json())
        return
    if args.command == "replay-proof":
        from oracle.data.broker_clock import BrokerClock
        from oracle.data.calendar import TradingCalendar
        from oracle.data.clock_proof import require_seasonal_proof
        from oracle.replay.golden import read_golden
        from oracle.replay.harness import replay_proof

        if not config.data.canonical_broker:
            parser.error("Pin canonical_broker before running proof")
        if None in (args.input, args.calendar, args.start_ms, args.end_ms):
            parser.error("Proof requires --input --calendar --start-ms --end-ms")
        clock = BrokerClock.load(Path(config.data.broker_clock_path))
        require_seasonal_proof(
            Path(config.data.clock_proof_path), config.data.canonical_broker, clock.version
        )
        bars = read_golden(
            args.input,
            config.data.canonical_broker,
            clock.version,
            config.data.canonical_server or clock.server,
        )
        calendar = TradingCalendar.model_validate_json(args.calendar.read_text())
        if calendar.canonical_broker != clock.broker or calendar.clock_version != clock.version:
            parser.error("clock changed, rederive calendar from UTC bars")
        print(json.dumps(replay_proof(bars, calendar, args.start_ms, args.end_ms), sort_keys=True))
        return
    configure_logging(Path(config.log_path))
    if args.command in ("clock-derive", "clock-proof"):
        from oracle.data.clock_derivation import derive_history_clock
        from oracle.data.clock_proof import run_seasonal_proof
        from oracle.data.mt5_feed import MT5Feed
        from oracle.data.mt5_gateway import Mt5Gateway
        from oracle.data.vendor_feed import TwelveDataFeed

        key = os.environ.get("TWELVE_DATA_API_KEY")
        if not key:
            parser.error("Set TWELVE_DATA_API_KEY for independent UTC validation")
        try:
            api = Mt5Gateway(tick_poll_ms=config.data.tick_poll_ms)
        except ModuleNotFoundError:
            parser.error("Install engine[mt5] and open the local Exness MT5 terminal")
        vendor = TwelveDataFeed(key)
        # Clock repair acquires untouched epochs without using a stale projection.
        feed = MT5Feed(api, config.data, vendor if args.command == "clock-proof" else None)
        try:
            feed.startup()
            if args.command == "clock-derive":
                if None in (args.start_ms, args.end_ms):
                    parser.error("Historical derivation requires --start-ms and --end-ms in UTC")
                feed.raw_history(
                    "M1",
                    args.start_ms + min(config.data.expected_offset_s) * 1000,
                    args.end_ms + max(config.data.expected_offset_s) * 1000,
                )
                assert feed.store is not None
                raw = [bar for bar in feed.store.raw_history("M1") if bar.complete]
                clock = derive_history_clock(
                    raw,
                    vendor,
                    config.data.canonical_broker,
                    config.data.expected_offset_s,
                    feed.server_utc_offset_s,
                    feed.clock,
                )
                feed.store.reproject(clock)
                clock.save(Path(config.data.broker_clock_path))
                print(clock.canonical_json())
            else:
                print(
                    run_seasonal_proof(
                        feed, args.year, Path(config.data.clock_proof_path)
                    ).canonical_json()
                )
        finally:
            if feed.store is not None:
                feed.store.close()
            api.shutdown()
        return
    uvicorn.run(
        create_dashboard(config, args.config.parent / "strings"),
        host=config.dashboard.host,
        port=config.dashboard.port,
    )


if __name__ == "__main__":
    main()
