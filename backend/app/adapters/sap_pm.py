"""L6 SAP PM adapter placeholder; production connectivity is out of scope."""

from typing import Any

from app.adapters.base import CMMSAdapter


class SapPmCMMS(CMMSAdapter):
    """Implement SAP OData `API_MAINTENANCEORDER;v=2` with CSRF-token flow."""

    async def create_work_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("SAP PM integration is intentionally not implemented")

    async def update_status(self, work_order_id: str, status: str) -> dict[str, Any]:
        raise NotImplementedError("SAP PM integration is intentionally not implemented")

    async def get_open_work_orders(self, asset_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("SAP PM integration is intentionally not implemented")
