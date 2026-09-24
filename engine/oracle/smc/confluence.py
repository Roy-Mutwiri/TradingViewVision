"""Phase 2 owns smc.confluence; intentionally unavailable."""

from typing import NoReturn


def unavailable() -> NoReturn:
    """Explicit failure; never pretend a future service is working."""
    raise NotImplementedError("phase_2:smc.confluence")
