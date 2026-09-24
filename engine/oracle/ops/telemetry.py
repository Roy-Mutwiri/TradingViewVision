"""Rotating structured JSONL logging; no secrets or raw environment dumps."""

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


class CredentialFilter(logging.Filter):
    """Drop credential-shaped records, including structured args and tracebacks."""

    pattern = re.compile(
        r"(?i)(?:password|passwd|pwd|investor[_ -]?secret|api[_ -]?key)\s*['\"]?\s*[:=]"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            parts = record.getMessage() + " " + repr(record.args)
            if record.exc_info:
                parts += logging.Formatter().formatException(record.exc_info)
            return not self.pattern.search(parts)
        except Exception:
            return False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "t_ms": int(record.created * 1000),
                "level": record.levelname,
                "logger": record.name,
                "event": record.getMessage(),
                "exception": self.formatException(record.exc_info) if record.exc_info else None,
            },
            sort_keys=True,
        )


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CredentialFilter())
    root = logging.getLogger("oracle")
    root.setLevel(logging.INFO)
    for existing in root.handlers[:]:
        existing.close()
        root.removeHandler(existing)
    root.addHandler(handler)
