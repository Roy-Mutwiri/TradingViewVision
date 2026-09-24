"""Phase 9 owns distribution.telegram; intentionally unavailable."""

from typing import NoReturn


def unavailable() -> NoReturn:
    """Explicit failure; never pretend a future service is working."""
    raise NotImplementedError("phase_9:distribution.telegram")
