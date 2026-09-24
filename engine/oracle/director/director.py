"""Retention projection of verified candles. Time is an input; no invented SMC calls."""

import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from oracle.analysis.contracts import Call, CancelReason
from oracle.analysis.explanations import reason_strip
from oracle.analysis.ledger import CallLedger
from oracle.analysis.scoring import board
from oracle.director.contracts import (
    AudienceComment,
    Card,
    Hook,
    Level,
    RetentionFrame,
)
from oracle.director.moderation import display_handle, handle_key, normalized, safe_text
from oracle.director.timeline import Timeline
from oracle.models import Bar, DrawObject, content_hash, timeframe_ms


class Director:
    def __init__(
        self,
        timeline: Timeline | None = None,
        language: str = "en",
        ledger: CallLedger | None = None,
        day_boundary: str = "17:00 America/New_York",
        reason_strip_seconds: int = 20,
        max_pending_age_ms: int = 600_000,
    ) -> None:
        self.lock = threading.RLock()
        self.timeline = timeline or Timeline()
        self.language = language
        self.bar: Bar | None = None
        self.card: Card | None = None
        self.card_start_ms = 0
        self.last_answer_ms = -45000
        self.questions: deque[tuple[str, str, int]] = deque(maxlen=50)
        self.last_command: dict[str, int] = {}
        self.names: dict[str, str] = {}
        self.seen: set[str] = set()
        self.event_ids: deque[str] = deque(maxlen=5000)
        self.shouts: deque[tuple[str, str]] = deque(maxlen=50)
        self.shout: str | None = None
        self.shout_until = 0
        self.supporters: deque[str] = deque(maxlen=5)
        self.ledger = ledger or CallLedger()
        self._ledger_mtime_ns = self.ledger.path.stat().st_mtime_ns if self.ledger.path and self.ledger.path.exists() else 0
        self.day_boundary = day_boundary
        self.reason_strip_seconds = reason_strip_seconds
        self.max_pending_age_ms = max_pending_age_ms
        self.active_hook: tuple[str, str, int] | None = None
        self.segment: tuple[str, int] | None = None
        self.viewer_count: int | None = None
        self.viewer_at_ms = 0
        self.sample_ms = -10000
        self.started_ms: int | None = None
        self.comment: AudienceComment | None = None
        self.rehearsal = False
        self.analysis_bias = {"H4": "NOT ASSESSED", "H1": "NOT ASSESSED", "M15": "NOT ASSESSED"}
        self.analysis_levels: list[Level] = []
        self.zone: DrawObject | None = None
        self.zoom: dict[str, int | float] | None = None
        self.market_closed = False
        self.next_open_ms: int | None = None

    def set_session(self, closed: bool, next_open_ms: int | None = None) -> None:
        with self.lock:
            self.market_closed, self.next_open_ms = closed, next_open_ms

    def set_analysis(
        self, bias: dict[str, str], levels: list[Level], active_zone: DrawObject | None = None
    ) -> None:
        """Only an engine-produced, justified DrawObject may become an active zone."""
        with self.lock:
            if any(
                value not in {"BULLISH", "BEARISH", "NEUTRAL", "NOT ASSESSED"}
                for value in bias.values()
            ):
                raise ValueError("Invalid engine bias")
            if active_zone and (
                active_zone.shape != "ZONE" or len(active_zone.points) < 2 or not active_zone.reason
            ):
                raise ValueError("Active zone needs a justified rectangle")
            self.analysis_bias = dict(bias)
            self.analysis_levels = levels[:3]
            self.zone = active_zone

    def observe(self, bar: Bar | None, closed: list[Bar], now_ms: int) -> None:
        with self.lock:
            if self.started_ms is None:
                self.started_ms = now_ms
                self.timeline.append({"kind": "session", "action": "start", "at_ms": now_ms})
            if bar:
                self.bar = bar

    def create_call(self, call: Call) -> Call:
        """Engine-only creation: no audience result or unbounded commentary can score."""
        if call.day_boundary != self.day_boundary:
            raise ValueError("Call must use configured analytical trading-day boundary")
        return self.ledger.create(call)

    def cancel_call(self, call_id: str, reason: CancelReason) -> None:
        self.ledger.cancel(call_id, reason)

    def ingest(
        self,
        kind: str,
        handle: str,
        text: str,
        now_ms: int,
        event_id: str = "",
        viewer_count: int | None = None,
    ) -> bool:
        with self.lock:
            if kind == "viewers":
                if viewer_count is not None and viewer_count >= 0:
                    self.viewer_count, self.viewer_at_ms = viewer_count, now_ms
                return True
            if event_id:
                if event_id in self.event_ids:
                    return False
                self.event_ids.append(event_id)
            key = handle_key(handle)
            text = normalized(text)
            if key is None or not safe_text(text):
                return False
            name = display_handle(handle)
            self.names[key] = name
            if kind == "gift":
                self.supporters.append(name)
                self.shouts.append((name, "thank you · predictions stay free"))
                if not self.card or self.card.ends_ms <= now_ms:
                    self._card(
                        "THANKS",
                        name,
                        "Thank you",
                        "Support never buys access. Educational analysis is free for everyone.",
                        now_ms,
                        4000,
                    )
                return True
            if kind == "follow":
                self.shouts.append((name, "welcome to ORACLE"))
                return True
            if kind != "comment":
                return False
            if key not in self.seen:
                self.seen.add(key)
                self.shouts.append((name, "first comment · welcome"))
            if now_ms - self.last_command.get(key, -20000) < 20000:
                return False
            self.last_command[key] = now_ms
            self.comment = AudienceComment(
                handle=name, text=text, at_ms=now_ms, ends_ms=now_ms + 4000
            )
            command = text.upper()
            if command in {"!BIAS", "!LEVELS", "!SCORE", "!ZONE"} or "?" in text:
                self.questions.append((name, text, now_ms))
                self._answer_next(now_ms)
            return True

    def _card(
        self, kind: Any, handle: str, question: str, answer: str, now_ms: int, duration: int
    ) -> None:
        self.card = Card(
            id=content_hash([kind, handle, now_ms]),
            kind=kind,
            handle=handle,
            question=question,
            answer=answer,
            ends_ms=now_ms + duration,
        )
        self.card_start_ms = now_ms
        self.timeline.append(
            {
                "kind": "card",
                "action": "start",
                "at_ms": now_ms,
                "card": self.card.model_dump(mode="json"),
            }
        )

    def _answer_next(self, now_ms: int) -> None:
        if (
            now_ms - self.last_answer_ms < 45000
            or not self.questions
            or self.card
            and self.card.ends_ms > now_ms
        ):
            return

        def relevance(item: tuple[str, str, int]) -> tuple[int, int]:
            _, text, arrival = item
            value = text.casefold()
            score = (
                100
                if value.startswith("!")
                else sum(
                    10
                    for term in ("gold", "price", "level", "zone", "close", "bias", "score")
                    if term in value
                )
            )
            return score, -arrival

        index = max(range(len(self.questions)), key=lambda i: relevance(self.questions[i]))
        name, question, _ = self.questions[index]
        del self.questions[index]
        command = question.upper()
        if command == "!BIAS":
            kind, answer, duration = (
                "BIAS",
                " / ".join(f"{tf}: {value.lower()}" for tf, value in self.analysis_bias.items())
                + ". UT Bot is an indicator, not an SMC bias or trade call.",
                8000,
            )
        elif command == "!LEVELS":
            kind, answer, duration = (
                "LEVELS",
                " · ".join(
                    f"{level.label}: {level.price:,.{self.bar.digits if self.bar else 2}f}"
                    for level in self.levels()
                )
                or (
                    "Market closed: live levels are withheld. Replay and education continue."
                    if self.market_closed
                    else "No verified candle levels yet."
                ),
                13000,
            )
        elif command == "!SCORE":
            stats = board(self.ledger.rows, now_ms, self.day_boundary).last_20
            resolved = stats.wins + stats.losses
            kind, answer, duration = (
                "SCORE",
                f"Last 20: {stats.wins}W / {stats.losses}L; {stats.scratch} scratch; "
                f"{stats.never_triggered} never triggered; {stats.cancelled} cancelled; "
                f"{stats.void_data} void data. "
                + (f"{stats.hit_rate:.0%} of {resolved} resolved." if stats.hit_rate is not None
                   else "No wins or losses resolved yet."),
                13000,
            )
        elif command == "!ZONE":
            kind, duration = "ZONE", 6000
            if self.zone:
                answer = self.zone.reason
                times = [p.t_ms for p in self.zone.points]
                pad = timeframe_ms(self.bar.tf) * 8 if self.bar else 480000
                self.zoom = {
                    "from_ms": max(0, min(times) - pad),
                    "to_ms": max(times) + pad,
                    "ends_ms": now_ms + 6000,
                }
            else:
                answer = "No active SMC zone has been confirmed. No zone zoom or setup is implied."
        else:
            kind, duration = "ANSWER", 13000
            if (
                any(w in question.casefold() for w in ("price", "gold", "level", "buy", "sell"))
                and self.bar
                and not self.market_closed
            ):
                answer = f"Gold's verified candle is {self.bar.c:,.{self.bar.digits}f}. UT Bot labels are indicator flips, not trade calls."
            else:
                answer = "Educational chart analysis. !levels shows candle references; !score records engine analysis calls, including losses."
        self.last_answer_ms = now_ms
        self._card(kind, name, question, answer, now_ms, duration)

    def levels(self) -> list[Level]:
        if self.market_closed:
            return []
        if self.analysis_levels:
            return self.analysis_levels
        return (
            [
                Level(label="Candle high", price=self.bar.h),
                Level(label="Candle open", price=self.bar.o),
                Level(label="Candle low", price=self.bar.l),
            ]
            if self.bar
            else []
        )

    def _displayable_rows(self, now_ms: int):
        return [
            row
            for row in self.ledger.rows
            if row.call.state != "PENDING"
            or now_ms - row.call.created_ms < self.max_pending_age_ms
        ]

    def view(self, now_ms: int) -> RetentionFrame:
        # The live call producer is an independent owner. Refresh its append-only
        # file before projecting the scoreboard; no account data crosses here.
        if self.ledger.path:
            stamp = self.ledger.path.stat().st_mtime_ns if self.ledger.path.exists() else 0
            if stamp != self._ledger_mtime_ns:
                self.ledger = CallLedger(self.ledger.path, self.ledger.min_call_life_ms)
                self._ledger_mtime_ns = stamp
        with self.lock:
            if self.zoom and now_ms >= self.zoom["ends_ms"]:
                self.zoom = None
            if self.card and now_ms >= self.card.ends_ms:
                self.timeline.append(
                    {
                        "kind": "beat",
                        "type": "gift" if self.card.kind == "THANKS" else "answer",
                        "id": self.card.id,
                        "start_ms": self.card_start_ms,
                        "end_ms": self.card.ends_ms,
                    }
                )
                self.card = None
            self._answer_next(now_ms)
            if now_ms >= self.shout_until:
                if self.shout:
                    self.timeline.append(
                        {
                            "kind": "beat",
                            "type": "shout",
                            "start_ms": self.shout_until - 4000,
                            "end_ms": self.shout_until,
                        }
                    )
                self.shout = None
                if self.shouts:
                    name, message = self.shouts.popleft()
                    self.shout, self.shout_until = f"@{name} · {message}", now_ms + 4000
            if (
                self.viewer_count is not None
                and now_ms - self.sample_ms >= 10000
                and now_ms - self.viewer_at_ms <= 20000
            ):
                self.timeline.append(
                    {"kind": "viewers", "at_ms": now_ms, "count": self.viewer_count}
                )
                self.sample_ms = now_ms
            if self.market_closed:
                end = self.next_open_ms or now_ms
                hook = Hook(
                    id=f"session:{self.next_open_ms or 'pending'}",
                    kind="SESSION_OPEN",
                    headline="The market is closed. Watch the next session open.",
                    sub="If quotes return, the chart resumes. If the open is delayed, we stay in replay; no live levels are called.",
                    countdown_ms=max(0, end - now_ms),
                    ring_pct=0,
                    priority=90,
                    ends_ms=end,
                )
            else:
                end = (
                    self.bar.t_open_ms + timeframe_ms(self.bar.tf)
                    if self.bar
                    else ((now_ms // 60000) + 1) * 60000
                )
                if end <= now_ms:
                    end = ((now_ms // 60000) + 1) * 60000
                hook = Hook(
                    id=f"close:{end}",
                    kind="CANDLE_CLOSE",
                    headline="Watch the next confirmed candle close",
                    sub="Above its open: an up candle. Below: a down candle. Equal: unchanged; no direction claimed.",
                    countdown_ms=max(0, end - now_ms),
                    ring_pct=min(
                        1,
                        max(
                            0,
                            1 - (end - now_ms) / (timeframe_ms(self.bar.tf) if self.bar else 60000),
                        ),
                    ),
                    priority=0,
                    ends_ms=end,
                )
            if not self.active_hook or self.active_hook[0] != hook.id:
                if self.active_hook:
                    old_id, old_type, start = self.active_hook
                    self.timeline.append(
                        {
                            "kind": "beat",
                            "type": f"hook.{old_type}",
                            "id": old_id,
                            "start_ms": start,
                            "end_ms": now_ms,
                        }
                    )
                self.active_hook = (hook.id, hook.kind, now_ms)
                self.timeline.append(
                    {
                        "kind": "hook",
                        "action": "start",
                        "at_ms": now_ms,
                        "hook": hook.model_dump(mode="json"),
                    }
                )
            segment = (
                "VIEWER_ANSWER" if self.card else "LIVE_CHART"
            )
            if not self.segment or self.segment[0] != segment:
                if self.segment:
                    self.timeline.append(
                        {
                            "kind": "beat",
                            "type": f"segment.{self.segment[0]}",
                            "start_ms": self.segment[1],
                            "end_ms": now_ms,
                        }
                    )
                self.segment = (segment, now_ms)
            utc = datetime.fromtimestamp(now_ms / 1000, UTC)
            session = (
                "New York"
                if 8 <= utc.astimezone(ZoneInfo("America/New_York")).hour < 17
                else "London"
                if 7 <= utc.astimezone(ZoneInfo("Europe/London")).hour < 16
                else "Asia / overnight"
            )
            rows = self._displayable_rows(now_ms)
            return RetentionFrame(
                now_ms=now_ms,
                hook=hook,
                card=self.card,
                shout=self.shout,
                supporters=list(self.supporters),
                scoreboard=board(rows, now_ms, self.day_boundary),
                levels=self.levels() if not self.market_closed else [],
                session=session if not self.market_closed else "Market closed",
                language=self.language,
                bias=self.analysis_bias,
                zoom=self.zoom,
                rehearsal=self.rehearsal,
                comment=self.comment if self.comment and now_ms < self.comment.ends_ms else None,
                marks=[mark for row in rows
                       if self.bar and (mark := reason_strip(
                           row.call, now_ms,
                           row.call.created_ms // timeframe_ms(self.bar.tf) * timeframe_ms(self.bar.tf),
                           self.reason_strip_seconds, self.bar.digits))],
            )

    def close(self, now_ms: int) -> None:
        with self.lock:
            if self.active_hook:
                ident, kind, start = self.active_hook
                self.timeline.append(
                    {
                        "kind": "beat",
                        "type": f"hook.{kind}",
                        "id": ident,
                        "start_ms": start,
                        "end_ms": now_ms,
                    }
                )
                self.active_hook = None
            if self.segment:
                self.timeline.append(
                    {
                        "kind": "beat",
                        "type": f"segment.{self.segment[0]}",
                        "start_ms": self.segment[1],
                        "end_ms": now_ms,
                    }
                )
                self.segment = None
            if self.card:
                self.timeline.append(
                    {
                        "kind": "beat",
                        "type": "answer",
                        "start_ms": self.card_start_ms,
                        "end_ms": min(now_ms, self.card.ends_ms),
                    }
                )
            self.timeline.append({"kind": "session", "action": "end", "at_ms": now_ms})
