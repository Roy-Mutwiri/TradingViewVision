"""Run against the operator's local MT5 and actual independent UTC history."""

import os
import sys
from pathlib import Path

import pytest

from oracle.config import load_config
from oracle.data.clock_proof import season_window
from oracle.data.mt5_feed import MT5Feed
from oracle.data.mt5_gateway import Mt5Gateway
from oracle.data.vendor_feed import TwelveDataFeed

pytestmark = [
    pytest.mark.windows_live,
    pytest.mark.skipif(sys.platform != "win32", reason="MT5 is Windows-only; live proof not run"),
]


@pytest.fixture(scope="module")
def live_feed():
    key = os.environ.get("TWELVE_DATA_API_KEY")
    if not key:
        pytest.skip("Real clock proof requires TWELVE_DATA_API_KEY; no fixture substitute")
    try:
        api = Mt5Gateway()
    except ImportError:
        pytest.skip("Real clock proof requires local MT5 integration")
    root = Path(__file__).resolve().parents[3]
    config = load_config(root / "config/oracle.yaml")
    feed = MT5Feed(api, config.data, TwelveDataFeed(key))
    try:
        feed.startup()
        yield feed
    finally:
        if feed.store is not None:
            feed.store.close()
        api.shutdown()


@pytest.mark.parametrize("month", [1, 7], ids=["january", "july"])
def test_real_utc_argmax_matches_derived_clock(live_feed, month):
    year = int(os.environ.get("ORACLE_CLOCK_PROOF_YEAR", "2025"))
    start, end = season_window(year, month)
    raw = live_feed.raw_history("M1", start, end)
    assert len(raw) >= 500, "Need 500 real MT5 M1 bars"
    report = live_feed.verify_history_window(raw)
    assert live_feed.clock is not None
    assert report.offset_s == live_feed.clock.offset_ms_at(raw[0].t_broker_ms) // 1000
    assert report.correlation >= 0.95
