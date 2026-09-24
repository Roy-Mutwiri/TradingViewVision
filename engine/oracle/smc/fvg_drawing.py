"""Causal live FVG cache and DrawObject projection; forming bars never alter records."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from oracle.config import ZonesConfig
from oracle.models import Animation, Bar, DrawObject, Point, Style
from oracle.smc.imbalance import ImbalanceCursor, advance_imbalance, observe_fill
from oracle.smc.worklog import WorkDecision


class FVGDrawing:
    def __init__(self, config: ZonesConfig, audit_path: Path | None = None) -> None:
        self.cursor = ImbalanceCursor(config=config)
        self.decisions: list[WorkDecision] = []
        self.audit_path = audit_path
        self.audit_error: str | None = None
        self.audit_written = 0
        self.audit_seen: set[str] = set()
        if audit_path is not None and audit_path.exists():
            try:
                self.audit_seen = {str(json.loads(line)["id"]) for line in audit_path.read_text(encoding="utf-8").splitlines()}
            except (OSError, ValueError, KeyError) as error:
                self.audit_error = str(error)

    def _audit(self) -> None:
        if self.audit_path is None or self.audit_written == len(self.decisions):
            return
        decisions = [d for d in self.decisions[self.audit_written:] if d.id not in self.audit_seen]
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            if decisions:
                with self.audit_path.open("a", encoding="utf-8") as file:
                    file.write("".join(d.canonical_json()+"\n" for d in decisions))
            self.audit_seen.update(d.id for d in decisions)
            self.audit_written = len(self.decisions)
        except OSError as error:
            self.audit_error = str(error)

    def objects(self, bars: Sequence[Bar]) -> list[DrawObject]:
        if not bars:
            return []
        last = self.cursor.recent[-1].t_open_ms if self.cursor.recent else -1
        for bar in bars:
            if bar.complete and bar.t_open_ms > last:
                before_ids = {r.id for r in self.cursor.records}
                before_events = len(self.cursor.events)
                self.cursor = advance_imbalance(self.cursor, bar)
                for record in self.cursor.records:
                    if record.id not in before_ids:
                        g = record.geometry
                        self.decisions.append(WorkDecision(
                            id=f"marked:{record.id}", at_ms=record.born_ms, tf=g.tf,
                            object_id=record.id, action="MARKED",
                            label=f"marked {g.tf} {record.kind} {g.price_lo:,.2f} – {g.price_hi:,.2f}",
                            source_bars=g.source_bars, source_object_ids=g.source_object_ids))
                for event in self.cursor.events[before_events:]:
                    labels = {"CE_LOST": "CE lost", "INVERTED": "inverted", "INVALID": "invalid",
                              "MERGED": "merged", "MERGE_REJECTED": "merge rejected",
                              "REINVERSION_ATTEMPT": "re-inversion rejected"}
                    self.decisions.append(WorkDecision(
                        id=hashlib.blake2b(event.canonical_json().encode(), digest_size=8).hexdigest(),
                        at_ms=event.at_ms, tf=bar.tf, object_id=event.zone_id, action=event.kind,
                        label=f"{bar.tf} FVG · {labels[event.kind]}",
                        source_bars=(event.bar_index,), source_object_ids=(event.bar_id,)))
                last = bar.t_open_ms
        forming = bars[-1] if not bars[-1].complete else None
        records = sorted((r for r in self.cursor.records if r.renders and r.fill_pct < 1),
                         key=lambda r: (r.born_ms, r.id))
        records = records[-self.cursor.config.max_visible_per_tf.fvg:]
        output: list[DrawObject] = []
        for record in records:
            gap = record.geometry
            fill = record.fill_pct
            if forming is not None and forming.t_open_ms >= record.born_ms:
                fill = observe_fill(gap, forming, bar_idx=self.cursor.next_index,
                                    previous_fill=fill).fill_pct
            if fill >= 1:
                continue
            lo = gap.price_lo if gap.direction == "BULLISH" else gap.price_lo+fill*gap.size
            hi = gap.price_hi-fill*gap.size if gap.direction == "BULLISH" else gap.price_hi
            output.append(DrawObject(
                layer="L2", shape="ZONE",
                points=[Point(t_ms=gap.t_start_ms, price=gap.price_lo),
                        Point(t_ms=gap.created_ms, price=gap.price_hi)],
                style=Style(token="zone.fvg"), text_key=f"zone.fvg.{record.id}",
                text_args={"zone_id": record.id, "direction": gap.direction,
                           "tf": gap.tf, "kind": record.kind, "strength": record.strength,
                           "fill_pct": fill, "unfilled_lo": lo, "unfilled_hi": hi,
                           "ce": gap.ce, "weakened": record.weakened or record.ce_lost,
                           "end_ms": bars[-1].t_open_ms, "confirmed": True},
                state="BREAKER" if record.kind == "IFVG" else
                      "FRESH" if record.state == "FRESH" else "TOUCHED",
                ttl_ms=0, priority=4, z=0, anim=Animation(in_="none", loop=None),
                source_bars=list(gap.source_bars), confidence=1,
                reason="Confirmed three-candle imbalance", digits=bars[-1].digits,
            ))
        self._audit()
        return output
