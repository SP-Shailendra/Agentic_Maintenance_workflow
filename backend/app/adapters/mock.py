"""L6 deterministic in-memory integration mocks with demo failure injection."""

from typing import Any

from app.adapters.base import CMMSAdapter, InventoryAdapter, SchedulingAdapter
from app.schemas.domain import PartRequirement


class MockCMMS(CMMSAdapter):
    def __init__(self) -> None:
        self.work_orders: dict[str, dict[str, Any]] = {}
        self.cmms_down = False

    async def create_work_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.cmms_down:
            raise ConnectionError("CMMS mock is unavailable")
        correlation_id = str(payload["correlation_id"])
        if correlation_id not in self.work_orders:
            work_order_id = f"WO-{len(self.work_orders) + 1:05d}"
            self.work_orders[correlation_id] = {
                "wonum": work_order_id,
                "assetnum": payload["asset_id"],
                "siteid": payload["site_id"],
                "description": payload["summary"],
                "externalrefid": correlation_id,
                "status": "DRAFT",
                **payload,
            }
        return self.work_orders[correlation_id].copy()

    async def update_status(self, work_order_id: str, status: str) -> dict[str, Any]:
        for work_order in self.work_orders.values():
            if work_order["wonum"] == work_order_id:
                work_order["status"] = status
                return work_order.copy()
        raise KeyError(f"Unknown work order: {work_order_id}")

    async def get_open_work_orders(self, asset_id: str) -> list[dict[str, Any]]:
        return [
            order.copy()
            for order in self.work_orders.values()
            if order["assetnum"] == asset_id and order["status"] not in {"CLOSED", "REJECTED"}
        ]


class MockInventory(InventoryAdapter):
    def __init__(self, stock: dict[str, int] | None = None) -> None:
        self.stock = dict(stock or {})
        self.inventory_down = False
        self.reservations: dict[tuple[str, str], int] = {}

    async def check_availability(self, part: PartRequirement) -> dict[str, Any]:
        if self.inventory_down:
            raise ConnectionError("Inventory mock is unavailable")
        quantity = self.stock.get(part.part_number, 0)
        return {
            "part_number": part.part_number,
            "requested": part.quantity,
            "available": quantity,
            "all_available": quantity >= part.quantity,
        }

    async def reserve(self, correlation_id: str, part: PartRequirement) -> dict[str, Any]:
        if self.inventory_down:
            raise ConnectionError("Inventory mock is unavailable")
        key = (correlation_id, part.part_number)
        if key in self.reservations:
            return {
                "part_number": part.part_number,
                "quantity": self.reservations[key],
                "reserved": True,
            }
        available = self.stock.get(part.part_number, 0)
        if available < part.quantity:
            raise ValueError(f"Insufficient stock for {part.part_number}")
        self.stock[part.part_number] = available - part.quantity
        self.reservations[key] = part.quantity
        return {"part_number": part.part_number, "quantity": part.quantity, "reserved": True}


class MockScheduler(SchedulingAdapter):
    def __init__(self, technicians: list[dict[str, Any]] | None = None) -> None:
        self.technicians = technicians or []

    async def propose_assignment(self, required_skills: list[str]) -> dict[str, Any] | None:
        required = set(required_skills)
        candidates = [
            technician
            for technician in self.technicians
            if technician.get("available", True) and required <= set(technician.get("skills", []))
        ]
        if not candidates:
            return None
        technician = min(candidates, key=lambda item: len(set(item["skills"]) - required))
        return {
            "technician_id": technician["technician_id"],
            "name": technician["name"],
            "skill_match": sorted(required),
            "extra_skills": sorted(set(technician["skills"]) - required),
        }
