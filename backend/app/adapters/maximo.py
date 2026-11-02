"""L6 Maximo adapter placeholder; production connectivity is out of scope."""

from typing import Any

from app.adapters.base import CMMSAdapter


class MaximoCMMS(CMMSAdapter):
    """Implement against Maximo REST object structure `mxapiwodetail`.

    Production requests use the configured Maximo base URL, `apikey` header,
    and `lean=1`; credentials must be supplied through environment variables.
    """

    async def create_work_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Maximo integration is intentionally not implemented")

    async def update_status(self, work_order_id: str, status: str) -> dict[str, Any]:
        raise NotImplementedError("Maximo integration is intentionally not implemented")

    async def get_open_work_orders(self, asset_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("Maximo integration is intentionally not implemented")
