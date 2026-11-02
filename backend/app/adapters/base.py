"""L6 adapter interfaces for CMMS, inventory, and technician scheduling."""

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.domain import PartRequirement


class CMMSAdapter(ABC):
    @abstractmethod
    async def create_work_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or return the existing work order for its correlation ID."""

    @abstractmethod
    async def update_status(self, work_order_id: str, status: str) -> dict[str, Any]:
        """Update a work-order lifecycle status."""

    @abstractmethod
    async def get_open_work_orders(self, asset_id: str) -> list[dict[str, Any]]:
        """Return nonterminal work orders for an asset."""


class InventoryAdapter(ABC):
    @abstractmethod
    async def check_availability(self, part: PartRequirement) -> dict[str, Any]:
        """Read availability without reserving stock."""

    @abstractmethod
    async def reserve(self, correlation_id: str, part: PartRequirement) -> dict[str, Any]:
        """Commit a part reservation after human approval."""


class SchedulingAdapter(ABC):
    @abstractmethod
    async def propose_assignment(self, required_skills: list[str]) -> dict[str, Any] | None:
        """Propose the least-overqualified available technician."""
