"""Append-only JSONL sink of market frames for the LetsTalk speaker (docs/ORACLE_BRIDGE.md).

ORACLE emits; the speaker consumes. Nothing here reads back, and nothing here may affect trading.

SAFETY CONTRACT - this runs inside the live trading app, so it must never block, slow or crash the worker:

* Frames are built and written on a dedicated daemon thread. Nothing touches the analysis path.
* The queue is bounded and drops the OLDEST frame on backpressure. A slow or stopped disk costs a dropped
  frame, never a stalled producer. (Contrast `oracle.bus.EventBus`, which raises `BusOverflow` and blocks the
  publisher - deliberately not used here.)
* Every exception is swallowed and counted. `offer()` and the writer loop cannot raise into a caller.
* Disabled by default. An ORACLE with no speaker configured behaves exactly as it does today.

If the sink dies the worker carries on and the speaker simply sees staleness, which it already handles by
refusing to speak market facts at all.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

#: schema version of a sink row; the consumer refuses a version it does not know
FRAME_VERSION = 1


class SpeakerSink:
    """A bounded, drop-oldest, never-raising JSONL writer."""

    def __init__(
        self,
        directory: Path,
        *,
        queue_size: int = 64,
        max_bytes: int = 10_000_000,
        keep_files: int = 6,
    ) -> None:
        self.directory = directory
        self.max_bytes = max_bytes
        self.keep_files = keep_files
        self._queue: deque[dict[str, Any]] = deque(maxlen=max(1, queue_size))
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._path: Path | None = None
        self._written = 0
        self._latest: dict[str, Any] | None = None
        self.stats = {"offered": 0, "written": 0, "dropped": 0, "errors": 0, "rotations": 0}

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._path = self.directory / f"frames-{time.time_ns()}.jsonl"
        except Exception:  # noqa: BLE001 - a sink that cannot open must not stop the worker
            self.stats["errors"] += 1
            self._path = None
        self._thread = threading.Thread(target=self._run, name="oracle-speaker-sink", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # ------------------------------------------------------------------ producer side
    def offer(self, frame: dict[str, Any]) -> None:
        """Hand a frame to the writer. Never blocks, never raises, drops the oldest when full."""
        try:
            with self._lock:
                self.stats["offered"] += 1
                if len(self._queue) == self._queue.maxlen:
                    self._queue.popleft()  # drop-oldest: the newest market state is the useful one
                    self.stats["dropped"] += 1
                self._queue.append(frame)
                self._latest = frame
            self._wake.set()
        except Exception:  # noqa: BLE001
            self.stats["errors"] += 1

    def latest(self) -> dict[str, Any] | None:
        """The newest frame offered, for GET /state. Independent of whether it reached disk."""
        with self._lock:
            return self._latest

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until the queue has drained. For tests and shutdown; never called on the hot path."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._wake.set()
            with self._lock:
                if not self._queue:
                    return True
            time.sleep(0.01)
        return False

    # ------------------------------------------------------------------ writer side
    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(1.0)
            self._wake.clear()
            self._drain()
        self._drain()

    def _drain(self) -> None:
        while True:
            try:
                with self._lock:
                    if not self._queue:
                        return
                    frame = self._queue.popleft()
                self._write(frame)
            except Exception:  # noqa: BLE001 - one bad frame must not kill the writer
                self.stats["errors"] += 1
                return

    def _write(self, frame: dict[str, Any]) -> None:
        if self._path is None:
            self.stats["errors"] += 1
            return
        line = json.dumps(frame, ensure_ascii=False, allow_nan=False, default=str) + "\n"
        encoded = line.encode("utf-8")
        # One writer at a time. The writer thread owns this normally, but `flush()` and `stop()` can drain from
        # another thread, and two handles appending concurrently loses rows.
        with self._write_lock:
            if self._written + len(encoded) > self.max_bytes:
                self._rotate()
            with self._path.open("ab") as stream:
                stream.write(encoded)
            self._written += len(encoded)
            self.stats["written"] += 1

    def _rotate(self) -> None:
        self._path = self.directory / f"frames-{time.time_ns()}.jsonl"
        self._written = 0
        self.stats["rotations"] += 1
        try:  # keep the directory bounded; the speaker only ever reads the newest
            files = sorted(self.directory.glob("frames-*.jsonl"), key=lambda p: p.stat().st_mtime)
            for old in files[: max(0, len(files) - self.keep_files)]:
                old.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            self.stats["errors"] += 1
