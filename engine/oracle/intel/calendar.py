"""Phase 6 owns intel.calendar; intentionally unavailable."""

from typing import NoReturn


def unavailable() -> NoReturn:
    """Explicit failure; never pretend a future service is working."""
    raise NotImplementedError("phase_6:intel.calendar")
