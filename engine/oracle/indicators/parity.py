"""Same-feed UT Bot verification against exported TradingView/OANDA reference labels."""

from typing import Sequence

from oracle.indicators.ut_bot import ut_bot
from oracle.models import Bar, Contract, Millis


class ReferenceLabels(Contract):
    feed: str
    key: float = 1
    atr_period: int = 10
    heikin_ashi: bool = False
    buy: list[Millis]
    sell: list[Millis]


def verify_oanda_labels(bars: Sequence[Bar], reference: ReferenceLabels) -> dict[str, object]:
    if reference.feed != "OANDA:XAUUSD":
        raise ValueError(
            "Parity needs OANDA:XAUUSD input and labels; Exness cannot prove OANDA parity"
        )
    if not bars or not all(b.complete for b in bars):
        raise ValueError("Parity needs closed bars with the same ATR warm-up prefix as TradingView")
    if any(b.source != "twelve_data" for b in bars):
        raise ValueError(
            "Real OANDA parity requires vendor-origin bars, never Exness or synthetic input"
        )
    values = ut_bot(bars, reference.key, reference.atr_period, reference.heikin_ashi)
    buy = [b.t_open_ms for b, v in zip(bars, values) if v.buy]
    sell = [b.t_open_ms for b, v in zip(bars, values) if v.sell]
    valid_from = (
        bars[3 * reference.atr_period].t_open_ms
        if len(bars) > 3 * reference.atr_period
        else bars[-1].t_open_ms + 1
    )
    expected_buy = [t for t in reference.buy if t >= valid_from]
    expected_sell = [t for t in reference.sell if t >= valid_from]
    if buy != expected_buy or sell != expected_sell:
        raise ValueError(
            f"Same-feed label mismatch: missing buy {sorted(set(reference.buy) - set(buy))}, extra buy {sorted(set(buy) - set(reference.buy))}, missing sell {sorted(set(reference.sell) - set(sell))}, extra sell {sorted(set(sell) - set(reference.sell))}"
        )
    return {
        "feed": reference.feed,
        "bars": len(bars),
        "buy": len(buy),
        "sell": len(sell),
        "matched": True,
    }
