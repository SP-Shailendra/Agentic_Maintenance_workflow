import asyncio

from app.adapters.mock import MockCMMS, MockInventory, MockScheduler
from app.schemas.domain import PartRequirement


def test_cmms_create_is_idempotent_by_correlation_id() -> None:
    cmms = MockCMMS()
    payload = {
        "correlation_id": "same-id",
        "asset_id": "WD-001",
        "site_id": "S1",
        "summary": "Inspect",
    }
    first = asyncio.run(cmms.create_work_order(payload))
    second = asyncio.run(cmms.create_work_order(payload))
    assert first["wonum"] == second["wonum"]
    assert len(cmms.work_orders) == 1


def test_inventory_check_is_read_only_and_reserve_decrements_once() -> None:
    inventory = MockInventory({"BRG-101": 3})
    part = PartRequirement(part_number="BRG-101", description="Bearing", quantity=2, unit_cost=30)
    assert asyncio.run(inventory.check_availability(part))["available"] == 3
    assert inventory.stock["BRG-101"] == 3
    asyncio.run(inventory.reserve("corr", part))
    asyncio.run(inventory.reserve("corr", part))
    assert inventory.stock["BRG-101"] == 1


def test_scheduler_requires_every_skill_and_minimizes_extra_skills() -> None:
    scheduler = MockScheduler(
        [
            {
                "technician_id": "tech-a",
                "name": "A",
                "skills": ["VIB", "MECH", "ELEC"],
                "available": True,
            },
            {"technician_id": "tech-b", "name": "B", "skills": ["VIB", "MECH"], "available": True},
        ]
    )
    assert asyncio.run(scheduler.propose_assignment(["VIB", "MECH", "ELEC"])) == {
        "technician_id": "tech-a",
        "name": "A",
        "skill_match": ["ELEC", "MECH", "VIB"],
        "extra_skills": [],
    }
    assert asyncio.run(scheduler.propose_assignment(["HVAC"])) is None