"""Versioned, effective-dated broker wall-clock normalization.

No IANA DST rule is assigned to a broker. Offset coverage is total; confidence
records which history has been examined without blocking ingestion.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from oracle.models import Contract, Millis, Text

ALLOWED_OFFSETS = frozenset({0, 3600, 7200, 10800, -18000})
log = logging.getLogger(__name__)


def derive_offset(tick_time_s: int, now_s: float) -> int:
    offset = round((tick_time_s - now_s) / 900) * 900
    if offset not in ALLOWED_OFFSETS:
        raise ValueError(f"HALTED: unsupported server UTC offset {offset}")
    return offset


Confidence = Literal["MEASURED", "DERIVED", "ASSUMED"]


class OffsetSpan(Contract):
    from_broker_ms: int | None
    to_broker_ms: int | None
    offset_s: int
    confidence: Confidence


class BrokerClock(Contract):
    broker: Text
    server: str = ""
    spans: tuple[OffsetSpan, ...] = Field(min_length=1)
    version: int = Field(ge=1, strict=True)
    measured_from_broker_ms: int | None = None
    derivation: Literal["measured", "vendor_aligned", "manual_override"] = "measured"

    @model_validator(mode="before")
    @classmethod
    def migrate_transitions(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "transitions" not in value:
            return value
        payload = dict(value)
        table = payload.pop("transitions")
        if not table or any(b[0] <= a[0] for a, b in zip(table, table[1:])):
            raise ValueError("Clock transitions must be ordered and unique")
        first = table[0][0]
        confidence = "MEASURED" if payload.get("derivation") == "measured" else "DERIVED"
        spans = []
        if confidence == "DERIVED" and first > 0:
            spans.append(
                dict(
                    from_broker_ms=None,
                    to_broker_ms=first,
                    offset_s=table[0][1],
                    confidence="ASSUMED",
                )
            )
        for i, (t, offset) in enumerate(table):
            spans.append(
                dict(
                    from_broker_ms=None if i == 0 and not spans else t,
                    to_broker_ms=table[i + 1][0] if i + 1 < len(table) else None,
                    offset_s=offset,
                    confidence=confidence,
                )
            )
        payload["spans"] = spans
        payload.setdefault("measured_from_broker_ms", first if confidence == "MEASURED" else None)
        return payload

    @model_validator(mode="after")
    def validate_table(self) -> Self:
        if self.spans[0].from_broker_ms is not None or self.spans[-1].to_broker_ms is not None:
            raise ValueError("Clock spans must cover all time")
        for i, span in enumerate(self.spans):
            if span.offset_s not in ALLOWED_OFFSETS:
                raise ValueError("HALTED: unsupported historical offset")
            if (
                span.from_broker_ms is not None
                and span.to_broker_ms is not None
                and span.to_broker_ms <= span.from_broker_ms
            ):
                raise ValueError("Clock spans must be ordered and gapless")
            if i and (
                span.from_broker_ms is None or self.spans[i - 1].to_broker_ms != span.from_broker_ms
            ):
                raise ValueError("Clock spans must be ordered and gapless")
        return self

    @property
    def transitions(self) -> tuple[tuple[int, int], ...]:
        # Compatibility view for historical derivation, not coverage lookup.
        return tuple(
            (
                s.from_broker_ms
                if s.from_broker_ms is not None
                else self.measured_from_broker_ms or 0,
                s.offset_s,
            )
            for s in self.spans
            if s.confidence != "ASSUMED"
        )

    def _span(self, t_broker_ms: int) -> OffsetSpan:
        index = bisect_right(
            [int(s.from_broker_ms) for s in self.spans[1:] if s.from_broker_ms is not None],
            t_broker_ms,
        )
        return self.spans[index]

    def offset_ms_at(self, t_broker_ms: int) -> int:
        return self._span(t_broker_ms).offset_s * 1000

    def confidence_at(self, t_broker_ms: int) -> Confidence:
        span = self._span(t_broker_ms)
        if (
            span.confidence == "MEASURED"
            and self.measured_from_broker_ms is not None
            and t_broker_ms < self.measured_from_broker_ms
        ):
            return "ASSUMED"
        return span.confidence

    def utc_ms(self, t_broker_ms: int) -> int:
        return t_broker_ms - self.offset_ms_at(t_broker_ms)

    def assert_expected(self, broker: str, expected: tuple[int, ...]) -> None:
        if self.broker != broker or any(s.offset_s not in expected for s in self.spans):
            raise ValueError(
                "HALTED: clock broker/offset is outside canonical broker configuration"
            )

    def measured(self, t_broker_ms: int, offset_s: int) -> BrokerClock:
        if offset_s not in ALLOWED_OFFSETS:
            raise ValueError("HALTED: unsupported measured offset")
        if self.offset_ms_at(t_broker_ms) == offset_s * 1000:
            return self
        last = self.spans[-1]
        if last.from_broker_ms is not None and t_broker_ms <= last.from_broker_ms:
            raise ValueError("HALTED: contradictory or stale clock measurement")
        spans = (
            *self.spans[:-1],
            OffsetSpan(
                from_broker_ms=last.from_broker_ms,
                to_broker_ms=t_broker_ms,
                offset_s=last.offset_s,
                confidence=last.confidence,
            ),
            OffsetSpan(
                from_broker_ms=t_broker_ms,
                to_broker_ms=None,
                offset_s=offset_s,
                confidence="MEASURED",
            ),
        )
        log.info(
            "Broker clock offset changed %s -> %s; clock_version=%s",
            last.offset_s,
            offset_s,
            self.version + 1,
        )
        return BrokerClock(
            broker=self.broker,
            server=self.server,
            spans=spans,
            version=self.version + 1,
            measured_from_broker_ms=self.measured_from_broker_ms
            if self.measured_from_broker_ms is not None
            else t_broker_ms,
            derivation="measured",
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(self.canonical_json(), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> BrokerClock:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class BoundaryEvidence(Contract):
    """Same observed session boundary in raw MT5 and independent UTC data.

    Reopened boundaries define the new offset after a weekend transition. Close
    evidence defines the pre-transition offset. Evidence must cover the oldest bar.
    """

    t_broker_ms: Millis
    t_utc_ms: Millis


def derive_transitions(
    broker: str, evidence: tuple[BoundaryEvidence, ...], previous: BrokerClock | None = None
) -> BrokerClock:
    if not evidence:
        raise ValueError("Historical derivation needs independently aligned boundary evidence")
    if any(b.t_broker_ms <= a.t_broker_ms for a, b in zip(evidence, evidence[1:])):
        raise ValueError("Boundary evidence must be ordered and unique")
    table: list[tuple[int, int]] = []
    for boundary in evidence:
        difference = boundary.t_broker_ms - boundary.t_utc_ms
        offset = round(difference / 900000) * 900
        if abs(difference - offset * 1000) > 60000 or offset not in ALLOWED_OFFSETS:
            raise ValueError("Session boundary cannot be aligned within one minute")
        if not table or table[-1][1] != offset:
            if table and abs(table[-1][1] - offset) != 3600:
                raise ValueError("Historical session offset jump is not exactly one hour")
            table.append((boundary.t_broker_ms, offset))
    transitions = tuple(table)
    if previous and previous.broker != broker:
        raise ValueError("Historical clock broker mismatch")
    candidate = BrokerClock.model_validate(
        dict(
            broker=broker,
            server=previous.server if previous else "",
            transitions=transitions,
            version=1,
            derivation="vendor_aligned",
        )
    )
    changed = previous is None or previous.spans != candidate.spans
    version = previous.version + int(changed) if previous else 1
    if previous is None or previous.transitions != transitions:
        for effective, offset in transitions:
            log.info(
                "Broker clock historical transition: broker=%s effective_from_broker_ms=%s offset_s=%s clock_version=%s",
                broker,
                effective,
                offset,
                version,
            )
    return candidate.model_copy(update={"version": version})
