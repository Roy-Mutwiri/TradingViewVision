"""Causal wick pivots; body-close breaks belong to structure.py.

High: h[i] > max(left) and h[i] >= max(right). Low: l[i] < min(left)
and l[i] <= min(right). This exact asymmetry elects the first bar of a
flat top/bottom. Only closed right bars confirm a pivot. Later confirmation
or major-pivot demotion never edits an earlier immutable snapshot.

ATR is the existing UT Bot rma_atr, carried incrementally and sampled at
the pivot bar, not the confirmation bar. Significance uses the preceding
opposite INTERNAL pivot. Major pivots additionally alternate, keeping the
higher of consecutive highs or the lower of consecutive lows. Seeds and
equal-price pivots remain unclassified and available in the internal layer.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import yaml
from pydantic import Field

from oracle.indicators.ut_bot import ATRState, rma_atr
from oracle.models import Bar, Contract, Timeframe, timeframe_ms
from oracle.smc.swing_contracts import EqualPivotPair, Pivot, SwingSnapshot


class SignificanceATR(Contract):
    default: float = Field(gt=0)
    M1: float | None = Field(default=None, gt=0)
    M5: float | None = Field(default=None, gt=0)
    M15: float | None = Field(default=None, gt=0)
    M30: float | None = Field(default=None, gt=0)
    H1: float | None = Field(default=None, gt=0)
    H4: float | None = Field(default=None, gt=0)
    D1: float | None = Field(default=None, gt=0)
    W1: float | None = Field(default=None, gt=0)
    MN1: float | None = Field(default=None, gt=0)


class SwingConfig(Contract):
    left: Literal[2] = 2
    right: Literal[2] = 2
    atr_period: int = Field(default=14, ge=1)
    eq_tolerance_atr: float = Field(default=0.10, ge=0)
    significance_atr: SignificanceATR = SignificanceATR(default=1.0, M1=1.4, M5=1.2, M15=1.0, H1=0.8, H4=0.7)

    def threshold(self, tf: Timeframe) -> float:
        value: float | None = getattr(self.significance_atr, tf)
        return value if value is not None else self.significance_atr.default


def load_swing_config(path: Path) -> SwingConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "swings" not in raw:
        raise ValueError("weights.yaml must contain a swings mapping")
    return SwingConfig.model_validate(raw["swings"])


@dataclass(frozen=True)
class SwingCursor:
    """Immutable incremental carry; already evaluated history is never analysed again."""

    config: SwingConfig
    bars: tuple[Bar, ...]
    atr_state: ATRState
    snapshot: SwingSnapshot
    equal_groups: tuple[tuple[Pivot, ...], ...]


def _label(pivot: Pivot, previous: Pivot | None, tolerance: float) -> str | None:
    if previous is None or pivot.opposite_pivot_id is None:
        return None
    delta = pivot.price - previous.price
    if abs(delta) <= tolerance:
        return None
    return ("HH" if delta > 0 else "LH") if pivot.side == "HIGH" else ("HL" if delta > 0 else "LL")


class _Detector:
    """Private workspace of one pure evaluation; no globals or external state."""

    def __init__(self, config: SwingConfig) -> None:
        self.config = config
        self.bars: list[Bar] = []
        self.atr: list[float | None] = []
        self.atr_state = ATRState(config.atr_period)
        self.internal: list[Pivot] = []
        self.major: list[Pivot] = []
        self.equal_groups: list[list[Pivot]] = []
        self.equal_pairs: list[EqualPivotPair] = []
        self.last: dict[str, Pivot] = {}

    def geometry(self, idx: int, side: str, end: int) -> bool:
        candidate = self.bars[idx]
        left = self.bars[idx - self.config.left:idx]
        right = self.bars[idx + 1:end + 1]
        if side == "HIGH":
            return all(candidate.h > b.h for b in left) and all(candidate.h >= b.h for b in right)
        return all(candidate.l < b.l for b in left) and all(candidate.l <= b.l for b in right)

    def pivot(self, idx: int, side: Literal["HIGH", "LOW"], end: int, confirmed: bool) -> Pivot:
        bar = self.bars[idx]
        opposite = self.last.get("LOW" if side == "HIGH" else "HIGH")
        if opposite is not None and opposite.idx >= idx:
            opposite = next((p for p in reversed(self.internal) if p.side != side and p.idx < idx), None)
        atr = self.atr[idx]
        price = bar.h if side == "HIGH" else bar.l
        leg = abs(price - opposite.price) / atr if opposite is not None and atr else None
        source = tuple(range(idx - self.config.left, end + 1))
        pivot = Pivot(
            tf=bar.tf, digits=bar.digits, idx=idx, t_ms=bar.t_open_ms, price=price, side=side,
            kind=None, confirmed=confirmed,
            confirmed_at_idx=end if confirmed else None,
            confirmed_at_ms=self.bars[end].t_open_ms + timeframe_ms(bar.tf) if confirmed else None,
            atr=atr, leg_atr=leg,
            significant=leg is not None and leg >= self.config.threshold(bar.tf),
            opposite_pivot_id=opposite.id if opposite else None,
            gap_adjacent=idx > 0 and bar.t_open_ms - self.bars[idx - 1].t_open_ms > timeframe_ms(bar.tf),
            source_bars=source, source_object_ids=tuple(self.bars[j].id for j in source),
        )
        tolerance = (atr or 0) * self.config.eq_tolerance_atr
        return pivot.transition(kind=_label(pivot, self.last.get(side), tolerance))

    def add(self, pivot: Pivot) -> None:
        self.internal.append(pivot)
        tolerance = (pivot.atr or 0) * self.config.eq_tolerance_atr
        if pivot.atr is not None:
            group_index = next((i for i, group in enumerate(self.equal_groups)
                if group[0].side == pivot.side
                and max(abs(p.price - pivot.price) for p in group) <= tolerance), None)
            if group_index is None:
                self.equal_groups.append([pivot])
            else:
                group = self.equal_groups[group_index]
                group.append(pivot)
                pair = EqualPivotPair(
                    digits=pivot.digits, kind="EQH" if pivot.side == "HIGH" else "EQL",
                    price_mean=sum(p.price for p in group) / len(group),
                    pivot_ids=tuple(p.id for p in group), bar_indices=tuple(p.idx for p in group),
                    count=len(group), tolerance=tolerance,
                    source_object_ids=tuple(dict.fromkeys(i for p in group for i in p.source_object_ids)),
                )
                members = set(pair.pivot_ids)
                self.equal_pairs = [p for p in self.equal_pairs if not set(p.pivot_ids) < members]
                self.equal_pairs.append(pair)
        self.last[pivot.side] = pivot
        if not pivot.significant:
            return
        if self.major and self.major[-1].side == pivot.side:
            prior = self.major[-1]
            if (pivot.price <= prior.price if pivot.side == "HIGH" else pivot.price >= prior.price):
                return
            self.major.pop()
        previous = next((p for p in reversed(self.major) if p.side == pivot.side), None)
        self.major.append(pivot.transition(kind=_label(pivot, previous, tolerance)))

    def step(self, bar: Bar) -> None:
        if self.bars:
            previous = self.bars[-1]
            if not previous.complete or bar.t_open_ms <= previous.t_open_ms:
                raise ValueError("bars must be ordered, unique, and only the final bar may be forming")
            if bar.tf != previous.tf or bar.symbol != previous.symbol or bar.digits != previous.digits:
                raise ValueError("swing input must have one symbol, timeframe and precision")
        timeframe_ms(bar.tf)
        self.bars.append(bar)
        if bar.complete:
            values, self.atr_state = rma_atr((bar,), self.config.atr_period, state=self.atr_state, with_state=True)
            self.atr.append(values[0])
        else:
            self.atr.append(None)
            return
        end = len(self.bars) - 1
        idx = end - self.config.right
        if idx >= self.config.left:
            # Compute both sides before committing either; an outside bar has no wick ordering.
            sides: tuple[Literal["HIGH", "LOW"], ...] = ("HIGH", "LOW")
            candidates = [self.pivot(idx, side, end, True) for side in sides
                          if self.geometry(idx, side, end)]
            for pivot in candidates:
                self.add(pivot)

    def snapshot(self) -> SwingSnapshot:
        end = len(self.bars) - 1
        provisional = []
        sides: tuple[Literal["HIGH", "LOW"], ...] = ("HIGH", "LOW")
        for idx in range(max(self.config.left, end - self.config.right), end + 1):
            confirmed = end - idx >= self.config.right and self.bars[end].complete
            if confirmed:
                continue
            for side in sides:
                if self.geometry(idx, side, end):
                    provisional.append(self.pivot(idx, side, end, False))
        return SwingSnapshot(at_idx=end, internal=tuple(self.internal), major=tuple(self.major),
            provisional=tuple(provisional), equal_pairs=tuple(self.equal_pairs), atr=tuple(self.atr))


def swings(bars: Sequence[Bar], config: SwingConfig | None = None) -> SwingSnapshot:
    """Evaluate exactly the supplied prefix; the caller controls its information horizon."""
    detector = _Detector(config or SwingConfig())
    for bar in bars:
        detector.step(bar)
    return detector.snapshot()


def advance_swings(
    cursor: SwingCursor | None, bar: Bar, config: SwingConfig | None = None,
) -> SwingCursor:
    """Pure incremental step, including replacement of the final forming candle.

    Rehydrate only containers: ATR, significance and old pivots are not recomputed.
    Changing parameters requires a fresh cursor, never rewriting its history.
    """
    if cursor is not None and config is not None and cursor.config != config:
        raise ValueError("swing parameters changed; restart the primitive")
    detector = _Detector(cursor.config if cursor is not None else config or SwingConfig())
    if cursor is not None:
        detector.bars = list(cursor.bars)
        detector.atr_state = cursor.atr_state
        detector.atr = list(cursor.snapshot.atr)
        detector.internal = list(cursor.snapshot.internal)
        detector.major = list(cursor.snapshot.major)
        detector.equal_pairs = list(cursor.snapshot.equal_pairs)
        detector.equal_groups = [list(group) for group in cursor.equal_groups]
        for pivot in detector.internal:
            detector.last[pivot.side] = pivot
        if detector.bars and not detector.bars[-1].complete:
            if bar.t_open_ms != detector.bars[-1].t_open_ms:
                raise ValueError("close the forming candle before appending another")
            detector.bars.pop()
            detector.atr.pop()
    detector.step(bar)
    return SwingCursor(detector.config, tuple(detector.bars), detector.atr_state,
                       detector.snapshot(), tuple(tuple(group) for group in detector.equal_groups))


def swing_stream(bars: Sequence[Bar], config: SwingConfig | None = None) -> tuple[SwingSnapshot, ...]:
    """One causal pass with immutable historical snapshots for the leak harness."""
    detector = _Detector(config or SwingConfig())
    result = []
    for bar in bars:
        detector.step(bar)
        result.append(detector.snapshot())
    return tuple(result)
