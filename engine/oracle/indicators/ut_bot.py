"""Deterministic UT Bot v4 trailing stop. ATR is Wilder RMA; EMA(src,1)=src."""

import math
from dataclasses import dataclass
from typing import Literal, Sequence, overload

from oracle.config import UTBotConfig
from oracle.models import Animation, Bar, Point, Style, UTBotDrawObject


@dataclass(frozen=True)
class UTValue:
    atr: float | None
    stop: float | None
    buy: bool
    sell: bool
    pos: int
    barbuy: bool
    barsell: bool
    warmup: bool
    confirmed: bool


@dataclass(frozen=True)
class ATRState:
    """Carry the same Wilder recurrence across closed-bar batches."""

    period: int
    count: int = 0
    seed_sum: float = 0.0
    previous_close: float | None = None
    value: float | None = None


@overload
def rma_atr(
    bars: Sequence[Bar], period: int = 10, *, state: ATRState | None = None,
    with_state: Literal[False] = False,
) -> list[float | None]: ...


@overload
def rma_atr(
    bars: Sequence[Bar], period: int = 10, *, state: ATRState | None = None,
    with_state: Literal[True],
) -> tuple[list[float | None], ATRState]: ...


def rma_atr(
    bars: Sequence[Bar], period: int = 10, *, state: ATRState | None = None,
    with_state: bool = False,
) -> list[float | None] | tuple[list[float | None], ATRState]:
    if period < 1:
        raise ValueError("ATR period must be positive")
    carry = state or ATRState(period)
    if carry.period != period:
        raise ValueError("ATR carry period differs from requested period")
    result: list[float | None] = []
    for bar in bars:
        tr = bar.h - bar.l
        if carry.previous_close is not None:
            tr = max(tr, abs(bar.h - carry.previous_close), abs(bar.l - carry.previous_close))
        count = carry.count + 1
        seed = carry.seed_sum + tr if count <= period else carry.seed_sum
        value = carry.value
        if count == period:
            value = seed / period
        elif count > period:
            assert value is not None
            value = (value * (period - 1) + tr) / period
        carry = ATRState(period, count, seed, bar.c, value)
        result.append(value)
    return (result, carry) if with_state else result


def ut_bot(
    bars: Sequence[Bar],
    key: float = 1.0,
    atr_period: int = 10,
    heikin: bool = False,
    confirm_on_close: bool = True,
) -> list[UTValue]:
    if not math.isfinite(key) or key <= 0:
        raise ValueError("UT Bot key must be finite and positive")
    if any(b.t_open_ms <= a.t_open_ms for a, b in zip(bars, bars[1:])):
        raise ValueError("UT Bot bars must be ordered and unique")
    if any(not b.complete for b in bars[:-1]):
        raise ValueError("Only the last UT Bot bar may be forming")
    src = [(b.o + b.h + b.l + b.c) / 4 if heikin else b.c for b in bars]
    atr = rma_atr(bars, atr_period)
    stop: list[float | None] = [None] * len(bars)
    result = []
    pos = 0
    for i, bar in enumerate(bars):
        value = atr[i]
        buy = sell = False
        warmup = i < 3 * atr_period
        if value is not None:
            loss = key * value
            prev = stop[i - 1] if i and stop[i - 1] is not None else 0.0
            assert prev is not None
            prior = src[i - 1] if i else src[i]
            if src[i] > prev and prior > prev:
                current = max(prev, src[i] - loss)
            elif src[i] < prev and prior < prev:
                current = min(prev, src[i] + loss)
            elif src[i] > prev:
                current = src[i] - loss
            else:
                current = src[i] + loss
            stop[i] = current
            # Original Pine ema(src,1) is identity, so crossover uses src directly.
            if i and stop[i - 1] is not None and not warmup:
                buy = prior <= prev and src[i] > current
                sell = prior >= prev and src[i] < current
            # pos belongs to bar colouring only, never the signal conditions.
            if prior < prev and src[i] > prev:
                pos = 1
            elif prior > prev and src[i] < prev:
                pos = -1
        # A forming flip is always provisional, including the intrabar preview mode.
        # confirm_on_close controls the confirmed buy/sell output; previews are derived below.
        confirmed = bar.complete
        if confirm_on_close and not confirmed:
            buy = sell = False
        trailing = stop[i]
        result.append(
            UTValue(
                value,
                trailing,
                buy,
                sell,
                pos,
                trailing is not None and src[i] > trailing,
                trailing is not None and src[i] < trailing,
                warmup,
                confirmed,
            )
        )
    return result


def draw_ut_bot(
    bars: Sequence[Bar],
    settings: UTBotConfig,
    values: Sequence[UTValue] | None = None,
    *,
    limit: int | None = None,
) -> list[UTBotDrawObject]:
    if not settings.enabled or not bars:
        return []
    series = (
        values
        if values is not None
        else ut_bot(bars, settings.key, settings.atr_period, settings.heikin_ashi, False)
    )
    objects = []
    for i, (bar, value) in enumerate(zip(bars, series)):
        if value.warmup or not (value.buy or value.sell):
            continue
        direction: Literal["BULLISH", "BEARISH"] = "BULLISH" if value.buy else "BEARISH"
        token = "utbot.buy" if value.buy else "utbot.sell"
        objects.append(
            UTBotDrawObject(
                tf=bar.tf,
                t_open_ms=bar.t_open_ms,
                direction=direction,
                digits=bar.digits,
                layer="L2",
                shape="LABEL",
                points=[Point(t_ms=bar.t_open_ms, price=bar.l if value.buy else bar.h)],
                style=Style(token=token if bar.complete else "utbot.provisional"),
                text_key=f"indicator.{token}" if bar.complete else "indicator.utbot.provisional",
                text_args={
                    "warmup": value.warmup,
                    "confirmed": bar.complete,
                    "direction": direction,
                },
                state="FRESH",
                ttl_ms=0,
                priority=0,
                z=0,
                anim=Animation(in_="none", loop=None),
                reason=("forming, not confirmed: " if not bar.complete else "")
                + f"close {bar.c:.{bar.digits}f} crossed {'above' if value.buy else 'below'} UT stop {value.stop:.{bar.digits}f} (ATR {value.atr:.{bar.digits}f}, k={settings.key})",
                source_bars=[i],
                confidence=0,
                warmup=value.warmup,
                confirmed=bar.complete,
            )
        )
    budget = settings.label_budget if limit is None else limit
    return objects[-budget:]  # Independent indicator allocation; oldest evicted first.
