"""Bounded asyncio fan-out. Overflow is explicit, never silent event loss."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from oracle.models import WireEvent


class BusOverflow(RuntimeError):
    """A slow subscriber must reconnect and request a fresh snapshot."""


class EventBus:
    def __init__(self, capacity: int = 1024) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._queues: set[asyncio.Queue[WireEvent]] = set()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[WireEvent]]:
        queue: asyncio.Queue[WireEvent] = asyncio.Queue(self.capacity)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.remove(queue)

    async def publish(self, event: WireEvent) -> None:
        # No await between preflight and enqueue: atomic within this event loop.
        if any(queue.full() for queue in self._queues):
            raise BusOverflow("subscriber capacity exhausted")
        for queue in self._queues:
            queue.put_nowait(event)
