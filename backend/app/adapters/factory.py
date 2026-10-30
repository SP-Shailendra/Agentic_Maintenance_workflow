"""L6 adapter factory, keeping orchestration independent of vendors."""

from app.adapters.base import CMMSAdapter, InventoryAdapter, SchedulingAdapter
from app.adapters.maximo import MaximoCMMS
from app.adapters.mock import MockCMMS, MockInventory, MockScheduler
from app.adapters.sap_pm import SapPmCMMS
from app.config import get_settings


def create_cmms_adapter() -> CMMSAdapter:
    adapter = get_settings().cmms_adapter.lower()
    if adapter == "mock":
        return MockCMMS()
    if adapter == "maximo":
        return MaximoCMMS()
    if adapter == "sap_pm":
        return SapPmCMMS()
    raise ValueError(f"Unsupported CMMS_ADAPTER: {adapter}")


def create_inventory_adapter() -> InventoryAdapter:
    adapter = get_settings().inventory_adapter.lower()
    if adapter == "mock":
        return MockInventory()
    raise ValueError(f"Unsupported INVENTORY_ADAPTER: {adapter}")


def create_scheduler_adapter() -> SchedulingAdapter:
    adapter = get_settings().scheduler_adapter.lower()
    if adapter == "mock":
        return MockScheduler()
    raise ValueError(f"Unsupported SCHEDULER_ADAPTER: {adapter}")