"""Real January/July UTC proofs; fixtures cannot produce this runtime artifact."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oracle.data.clock_alignment import AlignmentReport
from oracle.data.mt5_feed import MT5Feed
from oracle.models import Contract


class SeasonalClockProof(Contract):
    canonical_broker: str
    clock_version: int
    year: int
    january: AlignmentReport
    july: AlignmentReport


def season_window(year: int, month: int) -> tuple[int, int]:
    day = datetime(year, month, 15, 7, tzinfo=UTC)
    # An acquisition window encoded on the raw broker axis, not UTC conversion.
    day += timedelta(days=(2 - day.weekday()) % 7)
    start = int(day.timestamp()) * 1000
    return start, start + 500 * 60000


def run_seasonal_proof(feed: MT5Feed, year: int, output: Path) -> SeasonalClockProof:
    if feed.clock is None:
        raise RuntimeError("Initialize broker clock before seasonal proof")
    reports: dict[int, AlignmentReport] = {}
    for month in (1, 7):
        start, end = season_window(year, month)
        raw = feed.raw_history("M1", start, end)
        if len(raw) < 500:
            raise ValueError("Seasonal proof needs 500 actual MT5 M1 bars in each window")
        reports[month] = feed.verify_history_window(raw)
        logging.getLogger(__name__).info(
            "Real seasonal UTC proof: year=%s month=%s offset_s=%s",
            year,
            month,
            reports[month].offset_s,
        )
    proof = SeasonalClockProof(
        canonical_broker=feed.clock.broker,
        clock_version=feed.clock.version,
        year=year,
        january=reports[1],
        july=reports[7],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(proof.canonical_json(), encoding="utf-8")
    return proof


def require_seasonal_proof(path: Path, broker: str, clock_version: int) -> SeasonalClockProof:
    if not path.exists():
        raise ValueError("Phase 1 requires real January and July UTC correlation proofs")
    proof = SeasonalClockProof.model_validate_json(path.read_text(encoding="utf-8"))
    if proof.canonical_broker != broker or proof.clock_version != clock_version:
        raise ValueError("clock changed, regenerate UTC correlation proofs")
    for report in (proof.january, proof.july):
        if report.samples < 500 or report.correlation < 0.95:
            raise ValueError("Phase 1 seasonal UTC proof has insufficient samples")
    return proof
