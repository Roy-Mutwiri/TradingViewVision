"""Reject synthetic continuous gold variants before selection or ingestion."""

from oracle.transport.errors import EngineError


def assert_gold_symbol(symbol: str) -> None:
    if "247" in symbol.casefold() or "24/7" in symbol.casefold():
        raise EngineError(
            "SYMBOL_DENYLISTED",
            "24/7 gold variants are denied; select broker spot XAUUSDz.",
            {"symbol": symbol, "deny": ["XAUUSD247z"]},
            False,
        )
