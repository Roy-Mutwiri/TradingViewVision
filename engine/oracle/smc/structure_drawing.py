"""Existing DrawObject contract only; fixed history and one current protected level."""

from oracle.models import Animation, DrawObject, Point, Style
from oracle.smc.structure import StructureCursor


def structure_objects(cursor: StructureCursor | None, current_open_ms: int) -> list[DrawObject]:
    if cursor is None:
        return []
    bars = cursor.swings.bars
    result = []
    for event in cursor.events[-cursor.config.max_events_visible :]:
        result.append(
            DrawObject(
                layer="L2",
                shape="PATH",
                points=[
                    Point(t_ms=bars[event.broken_swing_idx].t_open_ms, price=event.level),
                    Point(t_ms=bars[event.break_bar_idx].t_open_ms, price=event.level),
                ],
                style=Style(token="structure.event"),
                text_key=f"structure.{event.id}",
                text_args={
                    "event_id": event.id,
                    "kind": "MSS" if event.is_mss else event.kind,
                    "direction": event.direction,
                    "tf": event.timeframe,
                    "confirmed": True,
                    "label_at_end": True,
                    "confirmed_at_ms": event.t_ms,
                    "dashed": True,
                    "weight": 1.5 if event.kind == "CHoCH" else 1,
                    "attention": event.kind == "CHoCH",
                },
                priority=3 if event.kind == "CHoCH" else 2,
                z=1,
                state="FRESH",
                ttl_ms=0,
                anim=Animation(in_="none", loop=None),
                source_bars=list(event.source_bars),
                confidence=1,
                reason="Confirmed body-close structure break",
                digits=bars[-1].digits,
            )
        )
    state = cursor.state
    low = state.trend == "BULLISH"
    price = state.protected_low if low else state.protected_high
    index = state.major_low_idx if low else state.major_high_idx
    if (
        cursor.config.show_protected_swing
        and price is not None
        and index is not None
        and state.last_event
    ):
        origin = Point(t_ms=bars[index].t_open_ms, price=price)
        result.append(
            DrawObject(
                layer="L2",
                shape="PATH",
                points=[origin, origin],
                style=Style(token="structure.protected"),
                text_key=f"protected.{state.last_event.id}",
                text_args={
                    "tf": bars[-1].tf,
                    "confirmed": True,
                    "end_ms": current_open_ms,
                    "opacity": 0.6,
                    "label_at_end": True,
                    "protected": True,
                    "direction": "DOWN" if low else "UP",
                },
                priority=3,
                z=0,
                state="FRESH",
                ttl_ms=0,
                anim=Animation(in_="none", loop=None),
                source_bars=[index],
                confidence=1,
                reason="Protected closed interval extreme",
                digits=bars[-1].digits,
            )
        )
    return result
