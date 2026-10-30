"""L1 bounded asyncio stream bus with back-pressure metrics."""

import asyncio
from collections.abc import AsyncIterator

from app.schemas.domain import TelemetryReading


class StreamBus:
    """In-process bus contract; a broker implementation can preserve this API."""

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[TelemetryReading] = asyncio.Queue(maxsize=maxsize)
        self.published = 0
        self.consumed = 0
        self.backpressure_waits = 0

    async def publish(self, reading: TelemetryReading) -> None:
        if self._queue.full():
            self.backpressure_waits += 1
        await self._queue.put(reading)
        self.published += 1

    async def consume(self) -> AsyncIterator[TelemetryReading]:
        while True:
            reading = await self._queue.get()
            self.consumed += 1
            self._queue.task_done()
            yield reading

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()