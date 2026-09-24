"""Real Phase 3a proof. Investor secret must already be in the native keychain."""

import os
import sys
from pathlib import Path

import pytest

from oracle.auth.contracts import ConnectRequest
from oracle.auth.profiles import NativeVault, ProfileStore
from oracle.config import load_config
from oracle.data.auth_session import LoginGate

pytestmark = [
    pytest.mark.windows_live,
    pytest.mark.skipif(
        sys.platform != "win32", reason="MT5 auth is Windows-only; live proof not run"
    ),
]


def test_real_phase3a_investor_login_preflight(tmp_path):
    if os.environ.get("ORACLE_RUN_WINDOWS_LIVE") != "1":
        pytest.skip("Set ORACLE_RUN_WINDOWS_LIVE=1 to authenticate the real local terminal")
    secret = NativeVault().get_password("oracle-studio", "ExnessKE-MT5Trial10:81740106:investor")
    if not secret:
        pytest.skip(
            "Investor password absent from native keychain; enter it locally in the desktop login gate"
        )
    root = Path(__file__).resolve().parents[3]
    config = load_config(root / "config/oracle.yaml")
    gate = LoginGate(config, root / "config", ProfileStore(tmp_path / "profiles.json"))
    request = ConnectRequest(
        login=81740106, password=secret, server="ExnessKE-MT5Trial10", remember=False
    )
    secret = ""
    try:
        result = gate.connect(request, lambda progress: None)
        assert result.error is None
        assert result.report.account.read_only is True
        assert result.report.account.trade_mode == "DEMO"
        assert result.report.clock.offset_s in (0, 3600)
        assert not any(check.state == "halt" for check in result.report.checks)
        assert gate.status().trade_mode == "DEMO"
    finally:
        gate.close()
