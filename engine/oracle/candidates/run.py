"""Run-scoped audit and deterministic projection; callers supply every timestamp."""

import json
from pathlib import Path

from oracle.candidates.contracts import Decision, EvalPoint
from oracle.candidates.lifecycle import CandidateEngine
from oracle.models import Animation, Bar, DrawObject, Point, Style
from oracle.smc.imbalance import observe_fill
from oracle.smc.liquidity_drawing import liquidity_objects
from oracle.smc.ob_drawing import ob_objects


class CandidateRun:
    def __init__(
        self,
        engine: CandidateEngine,
        directory: Path,
        metadata: dict[str, object],
        *,
        record_points: bool = True,
    ) -> None:
        self.engine, self.directory, self.record_points = engine, directory, record_points
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "metadata.json").write_text(
            json.dumps(metadata, sort_keys=True, indent=2), encoding="utf-8"
        )
        (directory / "seed-bars.jsonl").write_text(
            "".join(b.canonical_json() + "\n" for b in engine.closed), encoding="utf-8"
        )
        for name in (
            "evalpoints",
            "decisions",
            "closed-bars",
            "contexts",
            "render-trace",
            "coarse-spans",
        ):
            (directory / f"{name}.jsonl").touch()
        self.ob_rejections_written = 0
        (directory / "seed-minutes.jsonl").write_text("".join(b.canonical_json()+"\n" for b in engine.seed_minutes))
        (directory / "liquidity-seed-decisions.jsonl").write_text("".join(d.canonical_json()+"\n" for d in engine.liquidity_seed_decisions))
        (directory / "ob-rejections.jsonl").touch()
        (directory / "ob-seed-decisions.jsonl").write_text(
            "".join(d.canonical_json() + "\n" for d in engine.ob_seed_decisions)
        )
        (directory / "ob-seed-rejections.jsonl").write_text(
            "".join(json.dumps(d, sort_keys=True) + "\n" for d in engine.ob_seed_rejections)
        )

    def process(
        self,
        point: EvalPoint,
        *,
        parent_open_ms: int,
        closed_bar: Bar | None = None,
        data_gap: bool = False,
        closed_minutes: list[Bar] | tuple[Bar, ...] = (),
    ) -> list[Decision]:
        decisions = self.engine.process(
            point, parent_open_ms=parent_open_ms, closed_bar=closed_bar, data_gap=data_gap, closed_minutes=closed_minutes
        )
        if self.engine.ob:
            with (self.directory / "ob-rejections.jsonl").open("a", encoding="utf-8") as file:
                file.write(
                    "".join(
                        json.dumps(d, sort_keys=True) + "\n"
                        for d in self.engine.ob.rejections[self.ob_rejections_written :]
                    )
                )
            self.ob_rejections_written = len(self.engine.ob.rejections)
        if self.record_points:
            with (self.directory / "evalpoints.jsonl").open("a", encoding="utf-8") as file:
                file.write(point.canonical_json() + "\n")
            with (self.directory / "contexts.jsonl").open("a", encoding="utf-8") as file:
                file.write(
                    json.dumps(
                        dict(
                            seq=point.seq,
                            parent_open_ms=parent_open_ms,
                            data_gap=data_gap,
                            closed_bar=closed_bar.model_dump(mode="json") if closed_bar else None,
                            closed_minutes=[b.model_dump(mode="json") for b in closed_minutes],
                        ),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        if closed_bar is not None:
            with (self.directory / "closed-bars.jsonl").open("a", encoding="utf-8") as file:
                file.write(closed_bar.canonical_json() + "\n")
        if decisions:
            with (self.directory / "decisions.jsonl").open("a", encoding="utf-8") as file:
                file.write("".join(d.canonical_json() + "\n" for d in decisions))
            # Unbudgeted render intent: every removal has its own reasoned fade.
            with (self.directory / "render-trace.jsonl").open("a", encoding="utf-8") as file:
                for decision in decisions:
                    if decision.action == "DISCARD":
                        file.write(
                            json.dumps(
                                dict(
                                    decision_id=decision.id,
                                    object_id=decision.object_id,
                                    action="FADE",
                                    reason=decision.reason,
                                    fade_ms=600,
                                    reason_chip=True,
                                    seq=decision.seq,
                                ),
                                sort_keys=True,
                            )
                            + "\n"
                        )
        return decisions

    def drawings(self, end_ms: int, *, display_bar: Bar | None = None) -> list[DrawObject]:
        records = [c for c in self.engine.candidates.values() if c.state == "CANDIDATE"]
        records += [c for c in self.engine.candidates.values() if c.state == "DISCARDED"][-32:]
        objects: list[DrawObject] = []
        canonical = sorted(
            (r for r in self.engine.cursor.records if r.renders and r.fill_pct < 1),
            key=lambda r: (r.born_ms, r.id),
        )[-3:]
        for record in canonical:
            g = record.geometry
            fill = record.fill_pct
            # Raw ticks affect the read-only fill projection, never candidates or the record.
            if display_bar is not None:
                if display_bar.complete:
                    raise ValueError("tick fill projection must remain provisional")
                fill = observe_fill(
                    g, display_bar, bar_idx=len(self.engine.closed), previous_fill=fill
                ).fill_pct
            lo = g.price_lo if g.direction == "BULLISH" else g.price_lo + fill * g.size
            hi = g.price_hi - fill * g.size if g.direction == "BULLISH" else g.price_hi
            objects.append(
                DrawObject(
                    layer="L2",
                    shape="ZONE",
                    points=[
                        Point(t_ms=g.t_start_ms, price=g.price_lo),
                        Point(t_ms=g.created_ms, price=g.price_hi),
                    ],
                    style=Style(token="zone.fvg"),
                    text_key=f"zone.fvg.{record.id}",
                    text_args=dict(
                        zone_id=record.id,
                        direction=g.direction,
                        tf=g.tf,
                        kind=record.kind,
                        strength=record.strength,
                        fill_pct=fill,
                        unfilled_lo=lo,
                        unfilled_hi=hi,
                        ce=g.ce,
                        weakened=record.weakened or record.ce_lost,
                        end_ms=end_ms,
                        confirmed=True,
                        fidelity=record.fidelity,
                        born_ms=record.born_ms,
                    ),
                    state="BREAKER"
                    if record.kind == "IFVG"
                    else "FRESH"
                    if record.state == "FRESH"
                    else "TOUCHED",
                    ttl_ms=0,
                    priority=4,
                    z=0,
                    anim=Animation(in_="none", loop=None),
                    source_bars=list(g.source_bars),
                    confidence=1,
                    reason="Confirmed FVG; EvalPoint CLOSE only",
                    digits=self.engine.closed[-1].digits,
                )
            )
        for candidate in records:
            gap = candidate.geometry
            objects.append(
                DrawObject(
                    layer="L2",
                    shape="ZONE",
                    points=[
                        Point(t_ms=gap.t_start_ms, price=gap.price_lo),
                        Point(t_ms=gap.created_ms, price=gap.price_hi),
                    ],
                    style=Style(token="zone.fvg"),
                    text_key=f"candidate.{candidate.id}",
                    text_args=dict(
                        zone_id=candidate.id,
                        direction=gap.direction,
                        tf=gap.tf,
                        kind="FVG",
                        strength=1,
                        fill_pct=0,
                        unfilled_lo=gap.price_lo,
                        unfilled_hi=gap.price_hi,
                        ce=gap.ce,
                        end_ms=end_ms,
                        confirmed=False,
                        lifecycle=candidate.state,
                        fidelity=candidate.fidelity,
                        discard_reason=candidate.reason,
                        failed_criterion=candidate.criterion,
                        decision_id=candidate.decision_id,
                    ),
                    state="INVALID" if candidate.state == "DISCARDED" else "FRESH",
                    ttl_ms=0,
                    priority=4,
                    z=0,
                    anim=Animation(in_="none", loop=None),
                    source_bars=list(gap.source_bars),
                    confidence=0,
                    reason="Unconfirmed FVG candidate; never call evidence",
                    digits=self.engine.closed[-1].digits,
                )
            )
        if self.engine.ob:
            objects.extend(ob_objects(self.engine.ob, end_ms))
        if self.engine.liquidity:
            price = display_bar.c if display_bar else self.engine.forming.c if self.engine.forming else self.engine.closed[-1].c
            objects.extend(liquidity_objects(self.engine.liquidity, end_ms, price, len(self.engine.closed)))
        return objects
