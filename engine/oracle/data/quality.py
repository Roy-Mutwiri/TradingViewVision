"""Source provenance is visible in quality details."""

from oracle.models import Bar, DataQuality


def quality(
    bars: list[Bar], now_ms: int, spread_points: float, closed: bool = False
) -> DataQuality:
    stale = max(0, now_ms - bars[-1].t_open_ms - 60000) if bars else now_ms
    mixed = len({b.source for b in bars}) > 1
    if not bars:
        return DataQuality(
            state="NO_DATA", staleness_ms=0, spread_points=spread_points, detail="data.no_data"
        )
    return DataQuality(
        state="OK" if closed or stale <= 15000 else "STALE",
        staleness_ms=stale,
        spread_points=spread_points,
        detail="data.mixed_sources" if mixed else "data.closed" if closed else "data.live",
    )
