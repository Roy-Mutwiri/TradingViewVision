"""External feed proof: absent actual OANDA bars/reference labels is a skip, not a pass."""

import json
import os
from pathlib import Path

import pytest

from oracle.indicators.parity import ReferenceLabels, verify_oanda_labels
from oracle.models import Bar


def test_actual_oanda_vendor_bars_match_tradingview_labels():
    source = os.environ.get("ORACLE_OANDA_PARITY_INPUT")
    if not source:
        pytest.skip(
            "Actual OANDA vendor bars and TradingView labels not supplied; cross-feed proof pending"
        )
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    assert payload["feed"] == "OANDA:XAUUSD"
    bars = [Bar.model_validate(b) for b in payload["bars"]]
    reference = ReferenceLabels.model_validate(payload["reference"])
    assert verify_oanda_labels(bars, reference)["matched"]
