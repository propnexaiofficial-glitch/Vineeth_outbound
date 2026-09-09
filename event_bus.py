"""
event_bus.py — In-process async event bus for SSE fan-out.

Publishes events to all SSE subscribers for a given tenant.
"""
import asyncio
from typing import AsyncGenerator
from collections import defaultdict


class EventBus:
    def __init__(self):
        # tenant_id -> list of asyncio.Queue
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def publish(self, tenant_id: str, event: dict) -> None:
        """Fan-out event to all subscriber queues for this tenant."""
        for queue in self._subscribers.get(tenant_id, []):
            queue.put_nowait(event)

    async def subscribe(self, tenant_id: str) -> AsyncGenerator[dict, None]:
        """Yield events from an asyncio.Queue for this tenant."""
        queue = asyncio.Queue()
        self._subscribers[tenant_id].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers[tenant_id].remove(queue)


# Module-level singleton
bus = EventBus()
