"""Real broker parity. Missing credentials/clock evidence are explicit skips, never passes."""

import os
import sys
from pathlib import Path

import pytest

from oracle.auth.contracts import ConnectRequest
from oracle.auth.profiles import SERVICE, NativeVault, ProfileStore
from oracle.config import load_config
from oracle.data.auth_session import LoginGate
from oracle.data.live_chart import LiveChart

pytestmark = [
    pytest.mark.windows_live,
    pytest.mark.skipif(sys.platform != "win32", reason="MT5 is Windows-only"),
]


def test_real_mt5_fifty_closed_candles_and_timeframe_integrity(tmp_path):
    if os.environ.get("ORACLE_RUN_WINDOWS_LIVE") != "1":
        pytest.skip("Set ORACLE_RUN_WINDOWS_LIVE=1 for real MT5 parity")
    vault = NativeVault()
    key = "ExnessKE-MT5Trial10:81740106:investor"
    secret = vault.get_password(SERVICE, key)
    if not secret:
        pytest.skip("Investor profile is not present in Windows Credential Manager")
    root = Path(__file__).resolve().parents[3]
    config = load_config(root / "config/oracle.yaml")
    gate = LoginGate(config, root / "config", ProfileStore(tmp_path / "profiles.json", vault))
    try:
        request = ConnectRequest(
            login=81740106, password=secret, server="ExnessKE-MT5Trial10", remember=False
        )
        secret = ""
        result = gate.connect(request, lambda _: None)
        del request
        assert result.report is not None, "Live authentication/preflight must pass"
        gate.status()
        assert gate.feed and gate.feed.clock
        assert result.report.account.read_only
        chart = LiveChart(gate)
        for tf in ["M1", "H1", "M5"]:
            frame = chart.subscribe(tf)
            bars = frame.snapshot.bars
            assert len({b.t_open_ms for b in bars}) == len(bars)
            rows = gate.api.copy_rates_from_pos(
                gate.feed.broker_symbol, getattr(gate.api, f"TIMEFRAME_{tf}"), 0, len(bars)
            )
            assert len(rows) == len(bars)
            assert len(bars) >= 51
            for bar, row in zip(bars[-51:-1], rows[-51:-1]):
                assert bar.t_open_ms == gate.feed.clock.utc_ms(int(row["time"]) * 1000)
                for field, broker_field in [
                    ("o", "open"),
                    ("h", "high"),
                    ("l", "low"),
                    ("c", "close"),
                ]:
                    assert round(getattr(bar, field), bar.digits) == round(
                        float(row[broker_field]), bar.digits
                    )
        assert chart.debug().resolved_symbol != "XAUUSD247z"
    finally:
        gate.close()
