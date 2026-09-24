"""Phase 7 owns forecast.scenarios; intentionally unavailable."""

from typing import NoReturn


def unavailable() -> NoReturn:
    """Explicit failure; never pretend a future service is working."""
    raise NotImplementedError("phase_7:forecast.scenarios")
