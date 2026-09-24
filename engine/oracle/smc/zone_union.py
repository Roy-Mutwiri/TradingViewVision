"""Shared order-independent zone components and post-creation history horizon."""

from collections.abc import Sequence

from oracle.models import Bar


def overlap_components(
    bounds: Sequence[tuple[float, float]], keys: Sequence[tuple[object, ...]], threshold: float
) -> tuple[tuple[int, ...], ...]:
    parents = list(range(len(bounds)))

    def root(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, (lo, hi) in enumerate(bounds):
        for j in range(i + 1, len(bounds)):
            blo, bhi = bounds[j]
            if (
                keys[i] == keys[j]
                and max(0, min(hi, bhi) - max(lo, blo)) / min(hi - lo, bhi - blo) > threshold
            ):
                parents[root(j)] = root(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(bounds)):
        groups.setdefault(root(i), []).append(i)
    return tuple(tuple(v) for v in groups.values())


def post_creation_bars(bars: Sequence[Bar], created_ms: int) -> tuple[Bar, ...]:
    """Formation bars never fill or mitigate a newly confirmed union."""
    return tuple(b for b in bars if b.complete and b.t_open_ms >= created_ms)
