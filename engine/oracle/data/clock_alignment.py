"""Independent UTC alignment using equal-sized, timestamp-matched OHLC samples."""

import math
from statistics import fmean

from oracle.data.broker_bar import RawBrokerBar
from oracle.data.broker_clock import BrokerClock
from oracle.models import Bar, Contract

CANDIDATE_OFFSETS = tuple(range(-18000, 14401, 900))


class AlignmentReport(Contract):
    offset_s: int
    samples: int
    correlation: float
    return_correlation: float
    scores: dict[int, float]
    return_scores: dict[int, float]


def pearson(left: list[float], right: list[float]) -> float:
    x_mean, y_mean = fmean(left), fmean(right)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum((x - x_mean) ** 2 for x in left) * sum((y - y_mean) ** 2 for y in right)
    )
    if denominator == 0:
        raise ValueError("Clock alignment cannot use a constant-price sample")
    return numerator / denominator


def correlate_offsets(
    raw: list[RawBrokerBar], vendor: list[Bar], samples: int = 500
) -> AlignmentReport:
    if samples < 500 or len(raw) < samples:
        raise ValueError("Clock proof requires at least 500 M1 bars")
    selected = raw[:samples]
    if any(b.tf != "M1" or not b.complete for b in selected):
        raise ValueError("Alignment requires complete raw M1 bars")
    if any(b.t_broker_ms <= a.t_broker_ms for a, b in zip(selected, selected[1:])):
        raise ValueError("Alignment raw bars must be ordered and unique")
    if any(b.tf != "M1" or b.source != "twelve_data" or not b.complete for b in vendor):
        raise ValueError("Alignment requires complete independent UTC vendor M1 bars")
    reference = {b.t_open_ms: b for b in vendor}
    if len(reference) != len(vendor):
        raise ValueError("Duplicate vendor UTC timestamp")
    scores: dict[int, float] = {}
    returns: dict[int, float] = {}
    for offset in CANDIDATE_OFFSETS:
        matched = [reference.get(b.t_broker_ms - offset * 1000) for b in selected]
        if any(b is None for b in matched):
            # Never compare different-sized samples; acquire a wider vendor window.
            continue
        aligned = [b for b in matched if b is not None]
        component_scores, component_returns = [], []
        for key in ("o", "h", "l", "c"):
            x = [float(getattr(b, key)) for b in selected]
            y = [float(getattr(b, key)) for b in aligned]
            component_scores.append(pearson(x, y))
            component_returns.append(
                pearson([b - a for a, b in zip(x, x[1:])], [b - a for a, b in zip(y, y[1:])])
            )
        scores[offset] = fmean(component_scores)
        returns[offset] = fmean(component_returns)
    if len(scores) != len(CANDIDATE_OFFSETS):
        raise ValueError("UTC reference must cover all candidate offsets for the same 500 bars")
    winner = max(scores, key=lambda offset: scores[offset])
    return_winner = max(returns, key=lambda offset: returns[offset])
    runner_up = max(value for offset, value in returns.items() if offset != winner)
    if scores[winner] < 0.95 or winner != return_winner or returns[winner] - runner_up < 0.1:
        raise ValueError("HALTED: ambiguous UTC correlation; no distinct alignment spike")
    return AlignmentReport(
        offset_s=winner,
        samples=samples,
        correlation=scores[winner],
        return_correlation=returns[winner],
        scores=scores,
        return_scores=returns,
    )


def assert_alignment(report: AlignmentReport, clock: BrokerClock, raw: list[RawBrokerBar]) -> None:
    offsets = {clock.offset_ms_at(b.t_broker_ms) // 1000 for b in raw[: report.samples]}
    if offsets != {report.offset_s}:
        raise ValueError(
            f"HALTED: vendor UTC alignment wins at {report.offset_s}s; "
            "broker clock disagrees, rederive clock before ingestion"
        )
