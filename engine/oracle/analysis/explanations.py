"""Verbatim call evidence projected through the existing DrawObject contract."""

from typing import Literal

from oracle.analysis.contracts import Call
from oracle.models import Animation, DrawObject, Point, Style


def reason_strip(call: Call, now_ms: int, anchor_ms: int, seconds: int = 20,
                 digits: Literal[2, 3] = 2) -> DrawObject | None:
    until = call.created_ms + seconds * 1000
    if not call.reason_chain or not call.created_ms <= now_ms < until:
        return None
    lines = call.reason_chain[:3]
    return DrawObject(
        layer="L3", shape="LABEL", points=[Point(t_ms=anchor_ms, price=call.effective_entry_ref)],
        style=Style(token="analysis.reason"), text_key=f"analysis.reason.{call.id}",
        text_args={"label": "\n".join(lines), "call_id": call.id}, state="FRESH",
        ttl_ms=until-now_ms, priority=80, z=10, anim=Animation(in_="none", loop=None),
        reason="\n".join(lines), source_bars=[0], confidence=0, digits=digits,
    )
