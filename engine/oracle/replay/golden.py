"""Golden ranges are broker-specific and pure MT5 only."""

import json
from pathlib import Path

from oracle.models import Bar


def read_golden(path: Path, broker: str, clock_version: int, server: str) -> list[Bar]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("canonical_broker") != broker:
        raise ValueError("Golden canonical broker mismatch")
    if not server.strip() or payload.get("server") != server:
        raise ValueError("server changed or missing, regenerate")
    if payload.get("clock_version") != clock_version:
        if payload.get("provisional"):
            raise ValueError("clock refined, regenerate")
        raise ValueError("clock changed, regenerate")
    if payload.get("clock_confidence") not in ("MEASURED", "DERIVED", "ASSUMED"):
        raise ValueError("Golden clock confidence missing, regenerate")
    bars = [Bar.model_validate(bar) for bar in payload["bars"]]
    if not bars or any(bar.source != "mt5" for bar in bars):
        raise ValueError("Goldens require pure MT5 ranges")
    return bars
