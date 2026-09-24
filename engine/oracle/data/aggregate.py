"""Aggregate fully covered broker-clock buckets from authoritative stored M1."""

from oracle.data.broker_clock import BrokerClock
from oracle.data.candle_store import CandleStore
from oracle.models import Bar, Timeframe, timeframe_ms


def aggregate_m1(
    store: CandleStore, clock: BrokerClock, tf: Timeframe, count: int, end_utc_ms: int | None = None
) -> list[Bar]:
    if tf not in ("M5", "M15", "M30", "H1", "H4", "D1", "W1"):
        return []
    step = timeframe_ms(tf)
    phase = 4 * 86400000 if tf == "W1" else 0  # Monday broker wall-clock.
    offsets = [s.offset_s * 1000 for s in clock.spans]
    upper = end_utc_ms + max(offsets) if end_utc_ms is not None else 2**63 - 1
    lower = (
        max(0, upper - (count + 7) * step + min(offsets) - max(offsets))
        if end_utc_ms is not None
        else 0
    )
    rows = store.db.execute(
        """
        WITH input AS (
            SELECT t, t_broker_ms, payload,
              CAST(floor((t_broker_ms-?)/?)*?+? AS BIGINT) AS bucket
            FROM bars WHERE broker=? AND tf='M1' AND source='mt5' AND t_broker_ms>=? AND t_broker_ms<? AND CAST(json_extract(payload,'$.complete') AS BOOLEAN)
        )
        SELECT bucket, count(*), min(t_broker_ms), max(t_broker_ms),
          first(CAST(json_extract(payload,'$.o') AS DOUBLE) ORDER BY t),
          max(CAST(json_extract(payload,'$.h') AS DOUBLE)),
          min(CAST(json_extract(payload,'$.l') AS DOUBLE)),
          last(CAST(json_extract(payload,'$.c') AS DOUBLE) ORDER BY t),
          sum(CAST(json_extract(payload,'$.tick_volume') AS DOUBLE)),
          last(CAST(json_extract(payload,'$.digits') AS INTEGER) ORDER BY t)
        FROM input GROUP BY bucket HAVING count(*)=? AND max(t_broker_ms)-min(t_broker_ms)=?
        ORDER BY bucket DESC LIMIT ?
    """,
        [phase, step, step, phase, store.broker, lower, upper, step // 60000, step - 60000, count],
    ).fetchall()
    return [
        Bar(
            tf=tf,
            t_open_ms=clock.utc_ms(r[0]),
            o=r[4],
            h=r[5],
            l=r[6],
            c=r[7],
            tick_volume=r[8],
            digits=r[9],
            source="mt5",
            complete=True,
            clock_confidence=clock.confidence_at(r[0]),
        )
        for r in reversed(rows)
    ]
