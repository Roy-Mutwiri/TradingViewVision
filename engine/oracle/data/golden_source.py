"""Validate raw provenance at the data edge; export UTC-only golden bars."""

import json
from pathlib import Path

from oracle.data.broker_bar import BrokerBar
from oracle.data.broker_clock import BrokerClock


def write_golden(path: Path, broker: str, records: list[BrokerBar], clock: BrokerClock) -> None:
    if not broker.strip() or broker != clock.broker or not records or not clock.server.strip():
        raise ValueError("Goldens require a pinned broker and pure MT5 range")
    for record in records:
        if record.clock_version != clock.version or record != record.raw.normalize(clock):
            raise ValueError("clock changed, regenerate")
    path.write_text(
        json.dumps(
            {
                "canonical_broker": broker,
                "server": clock.server,
                "clock_version": clock.version,
                "clock_confidence": "ASSUMED"
                if any(r.bar.clock_confidence == "ASSUMED" for r in records)
                else "DERIVED"
                if any(r.bar.clock_confidence == "DERIVED" for r in records)
                else "MEASURED",
                "provisional": any(r.bar.clock_confidence == "ASSUMED" for r in records),
                "bars": [record.bar.model_dump(mode="json") for record in records],
            },
            sort_keys=True,
        )
    )
