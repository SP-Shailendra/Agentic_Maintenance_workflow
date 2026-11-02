"""L7 notification adapters for console logging and in-app event delivery."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Notifier(ABC):
    @abstractmethod
    async def notify(self, event_type: str, payload: dict[str, Any]) -> None:
        """Deliver a workflow notification without changing approval state."""


class ConsoleNotifier(Notifier):
    async def notify(self, event_type: str, payload: dict[str, Any]) -> None:
        logger.info("workflow_notification event_type=%s payload=%s", event_type, payload)


class EventNotifier(Notifier):
    def __init__(self, event_queue: Any) -> None:
        self.event_queue = event_queue

    async def notify(self, event_type: str, payload: dict[str, Any]) -> None:
        await self.event_queue.put({"type": event_type, "data": payload})
