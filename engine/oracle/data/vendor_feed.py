"""Twelve Data is gap-fill only; vendor volume is not MT5 tick volume."""

from datetime import UTC, datetime

import httpx

from oracle.models import Bar, Timeframe


class TwelveDataFeed:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def history(self, tf: Timeframe, start_ms: int, end_ms: int) -> list[Bar]:
        intervals = {
            "M1": "1min",
            "M5": "5min",
            "M15": "15min",
            "M30": "30min",
            "H1": "1h",
            "H4": "4h",
            "D1": "1day",
            "W1": "1week",
        }

        def stamp(t: int) -> str:
            return datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")

        response = httpx.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": "XAU/USD",
                "interval": intervals[tf],
                "start_date": stamp(start_ms),
                "end_date": stamp(end_ms),
                "timezone": "UTC",
                "apikey": self.api_key,
                "outputsize": 5000,
            },
            timeout=30,
        )
        if response.is_error:
            # HTTPStatusError includes the full request URL, including the API key.
            raise RuntimeError(f"Twelve Data request failed with HTTP {response.status_code}")
        payload = response.json()
        if payload.get("status") == "error":
            raise RuntimeError("Twelve Data gap-fill request failed")
        bars = []
        for row in payload.get("values", []):
            t = int(datetime.fromisoformat(row["datetime"]).replace(tzinfo=UTC).timestamp()) * 1000
            if start_ms <= t < end_ms:
                bars.append(
                    Bar(
                        tf=tf,
                        t_open_ms=t,
                        o=float(row["open"]),
                        h=float(row["high"]),
                        l=float(row["low"]),
                        c=float(row["close"]),
                        tick_volume=0,
                        source="twelve_data",
                        complete=True,
                    )
                )
        return sorted(bars, key=lambda b: b.t_open_ms)
