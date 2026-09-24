"""Tail GamechangerTalker's existing local LiveBridge JSONL; never fabricate live chat."""

import json
from pathlib import Path
from typing import Any

from oracle.director.director import Director


def ingest_record(director: Director, row: dict[str, Any], now_ms: int) -> bool:
    live = row.get("live", row)
    if not isinstance(live, dict):
        return False
    if row.get("kind") == "event" and row.get("action") != "submitted":
        return False
    kind = str(live.get("type", live.get("event_type", ""))).lower()
    if live.get("source") in {"replay", "mock", "rehearsal"}:
        director.rehearsal = True
    metadata = live.get("metadata", {})
    count = live.get(
        "viewer_count", metadata.get("viewer_count") if isinstance(metadata, dict) else None
    )
    return director.ingest(
        kind,
        str(live.get("username", live.get("name", ""))),
        str(live.get("text", "")),
        now_ms,
        str(live.get("event_id", "")),
        int(count) if count is not None else None,
    )


class GamechangerTail:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.file: Path | None = None
        self.position = 0
        self.pending = b""
        self.scan_ms = 0
        self.initial = True

    def poll(self, director: Director, now_ms: int) -> int:
        if self.path is None or not self.path.exists():
            return 0
        if now_ms - self.scan_ms >= 1000 or self.file is None:
            self.scan_ms = now_ms
            files = list(self.path.glob("*.jsonl")) if self.path.is_dir() else [self.path]
            candidate = max(files, key=lambda p: p.stat().st_mtime_ns) if files else None
            if candidate != self.file:
                self.file, self.pending = candidate, b""
                self.position = candidate.stat().st_size if candidate and self.initial else 0
                self.initial = False
        if self.file is None:
            return 0
        if self.file.stat().st_size < self.position:
            self.position, self.pending = 0, b""
        with self.file.open("rb") as stream:
            stream.seek(self.position)
            chunk = stream.read(131072)
            self.position = stream.tell()
        pieces = (self.pending + chunk).split(b"\n")
        self.pending = pieces.pop()[-65536:]
        accepted = 0
        for line in pieces:
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                stamp = row.get("arrived_at", row.get("t", row.get("timestamp")))
                if stamp is not None and abs(now_ms - round(float(stamp) * 1000)) > 30000:
                    continue
                accepted += int(ingest_record(director, row, now_ms))
            except (ValueError, TypeError, UnicodeError):
                continue
        return accepted
