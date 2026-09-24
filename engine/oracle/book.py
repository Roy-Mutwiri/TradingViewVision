
"""Deterministic history-backed narrative for the ORACLE Book layer."""

from __future__ import annotations

from typing import Any

from oracle.models import Animation, Bar, DrawObject, Point, Style, content_hash, timeframe_ms


def _price(value: float | None) -> str:
    return "--" if value is None else f"{value:,.2f}"


def _pct(value: float | None) -> str:
    return "n<30" if value is None else f"{value:.1f}%"


def _tf_ms(tf: str) -> int:
    try:
        return timeframe_ms(tf)  # type: ignore[arg-type]
    except Exception:
        return 900000


def _last_bars(frame_bars: list[Bar]) -> list[Bar]:
    return [b for b in frame_bars if b.complete] or frame_bars


def _current_day_range(bars: list[Bar]) -> tuple[float | None, float | None, float | None]:
    if not bars:
        return None, None, None
    lows = [b.l for b in bars[-96:]]
    highs = [b.h for b in bars[-96:]]
    return min(lows), max(highs), max(highs) - min(lows)


def _sentence(text: str, *source_ids: str, n: int | None = None) -> dict[str, Any]:
    return {"id": content_hash((text, source_ids, n, "book-sentence-v1")), "text": text, "source_ids": [s for s in source_ids if s], "n": n}


def build_book(*, tf: str, bars: list[Bar], thesis: dict[str, Any], objects: list[DrawObject], pools: list[Any], stats: dict[str, Any], now_ms: int) -> dict[str, Any]:
    closed = _last_bars(bars)
    live = closed[-1] if closed else None
    price = live.c if live else None
    day_lo, day_hi, day_range = _current_day_range(closed)
    adr = (stats.get("adr20") or {}).get("value")
    used = round(100 * day_range / adr, 1) if adr and day_range else None
    dr = thesis.get("dealing_range") or {}
    lo, hi, eq = dr.get("lo"), dr.get("hi"), dr.get("eq")
    range_pos = round(100 * (price - lo) / (hi - lo), 1) if price is not None and lo is not None and hi and hi > lo else None
    bias = str(thesis.get("bias") or "UNDEFINED")
    stage = str(thesis.get("stage") or "NO_BIAS")
    target = (thesis.get("targets") or [{}])[0] if isinstance(thesis.get("targets"), list) and thesis.get("targets") else {}
    alt = thesis.get("alternative") or {}
    invalidation = thesis.get("invalidation") or {}

    context_bits = []
    if lo is not None and hi is not None and range_pos is not None:
        context_bits.append(f"Range {_price(lo)} to {_price(hi)}  price at {range_pos:.0f}%")
    if used is not None:
        context_bits.append(f"today {used:.0f}% of ADR used")
    if stats.get("streaks", {}).get("counts", {}).get("3_down"):
        context_bits.append(f"3+ down-day samples {stats['streaks']['counts']['3_down']}")
    context = _sentence("  ".join(context_bits) or "Context warming up", "stat:adr20", "thesis:range", n=(stats.get("adr20") or {}).get("n"))

    events = [o for o in objects if o.style.token in {"structure.event", "liquidity.pool"}]
    story_parts = []
    for o in events[-4:]:
        label = str(o.text_args.get("kind") or o.text_args.get("name") or o.text_args.get("label") or o.style.token)
        level = o.text_args.get("level") or (o.points[0].price if o.points else None)
        story_parts.append(f"{label} {_price(float(level)) if level is not None else ''}".strip())
    story = _sentence("  ".join(story_parts) or "No completed sequence yet", *[str(o.id) for o in events[-4:]])

    
    cause = thesis.get("bias_cause") or {}
    cause_kind = str(cause.get("kind") or "structure")
    cause_level = cause.get("level")
    why_text = f"{bias} since {cause_kind} {_price(float(cause_level))}" if cause_level is not None else str(thesis.get("why") or "Bias not confirmed")
    why = _sentence(why_text, str(cause.get("event_id") or "thesis:bias"))

    below = [p for p in pools if getattr(p, "geometry", None) and price is not None and p.geometry.level < price]
    above = [p for p in pools if getattr(p, "geometry", None) and price is not None and p.geometry.level > price]
    below = sorted(below, key=lambda p: abs(price - p.geometry.level))[:2]
    above = sorted(above, key=lambda p: abs(price - p.geometry.level))[:2]
    where_parts = []
    for p in below + above:
        side = "below" if price is not None and p.geometry.level < price else "above"
        where_parts.append(f"{p.geometry.name} {_price(p.geometry.level)} {abs(price-p.geometry.level):.2f} {side}")
    where = _sentence("  ".join(where_parts) or "Arrays not in range", *[getattr(p, "id", "pool") for p in below + above])

    sweep_stats = stats.get("sweeps", {}).get("follow_after_reclaim", {})
    n = int(sweep_stats.get("n") or 0)
    follow_pct = (sweep_stats.get("pct") or {}).get("follow_1atr") if n >= 30 else None
    a_level = alt.get("trigger_level") or target.get("level")
    b_level = invalidation.get("level") or alt.get("invalidation_level")
    if a_level is not None and b_level is not None:
        next_text = f"A: close through {_price(a_level)}  1 ATR follow after reclaim {_pct(follow_pct)} (n={n})  B: invalidation {_price(b_level)}"
    else:
        next_text = str(thesis.get("if_then") or "Scenario waits for confirmed range").replace(" / ", "  ")
    nxt = _sentence(next_text, "stat:sweep_follow", str(target.get("id") or "target"), n=n)

    model = stats.get("daily_model") or {}
    model_n = int(model.get("n") or 0)
    phase = "ASIA" if live and live.t_open_ms % 86400000 < 7 * 3600000 else "LONDON" if live and live.t_open_ms % 86400000 < 12 * 3600000 else "NY"
    phase_label = f"{phase}  model {_pct(model.get('shape_pct') if model_n >= 30 else None)} (n={model_n})"

    book = {
        "id": content_hash((tf, now_ms // _tf_ms(tf), context["id"], story["id"], why["id"], where["id"], nxt["id"])),
        "tf": tf,
        "generated_ms": now_ms,
        "stats_id": stats.get("id"),
        "data_range": stats.get("data_range", {}),
        "context": context,
        "story": story,
        "why": why,
        "where": where,
        "next": nxt,
        "phase": {"label": phase_label, "source_ids": ["stat:daily_model"], "n": model_n},
        "stats": {
            "adr20": stats.get("adr20"),
            "london_takes_asia": stats.get("london_takes_asia"),
            "prior_day_levels": stats.get("prior_day_levels"),
            "sweeps": stats.get("sweeps"),
            "weekend_gaps": stats.get("weekend_gaps"),
            "daily_model": stats.get("daily_model"),
        },
        "slides": [
            {"type": "CONTEXT", "text": context["text"], "sentence_ids": [context["id"]]},
            {"type": "STORY", "text": story["text"], "sentence_ids": [story["id"]]},
            {"type": "WHY", "text": why["text"], "sentence_ids": [why["id"]]},
            {"type": "WHERE", "text": where["text"], "sentence_ids": [where["id"]]},
            {"type": "NEXT", "text": nxt["text"], "sentence_ids": [nxt["id"]]},
            {"type": "STATS", "text": f"ADR20 {_price(adr)} (n={(stats.get('adr20') or {}).get('n',0)})  London takes Asia high {_pct((stats.get('london_takes_asia') or {}).get('pct',{}).get('asia_high'))} (n={(stats.get('london_takes_asia') or {}).get('n',0)})", "sentence_ids": ["stat:adr20", "stat:london_takes_asia"]},
        ],
        "story_card": [context["text"], story["text"], why["text"], nxt["text"]],
    }
    return book


def book_draw_objects(book: dict[str, Any], bars: list[Bar]) -> list[DrawObject]:
    if not bars:
        return []
    last = bars[-1]
    label = book.get("phase", {}).get("label")
    if not label:
        return []
    price = last.h
    return [
        DrawObject(
            layer="L3",
            shape="LABEL",
            points=[Point(t_ms=last.t_open_ms, price=price)],
            style=Style(token="notebook.book"),
            text_key="book.phase",
            text_args={"label": label, "source_object_id": book.get("id", "book"), "label_at_end": True},
            state="FRESH",
            ttl_ms=0,
            priority=3,
            z=2,
            anim=Animation(in_="fade", loop=None),
            source_bars=[len(bars) - 1],
            confidence=1,
            reason="Book daily model phase from stats and session calendar",
            digits=last.digits,
        )
    ]
