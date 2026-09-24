"""Phase 9 owns ops.health; intentionally unavailable."""

from typing import NoReturn


def unavailable() -> NoReturn:
    """Explicit failure; never pretend a future service is working."""
    raise NotImplementedError("phase_9:ops.health")
