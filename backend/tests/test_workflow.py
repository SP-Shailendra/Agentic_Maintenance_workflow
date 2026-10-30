import asyncio
from datetime import UTC, datetime

import pytest

from app.agentweave.runner import WorkflowRunner
from app.schemas.domain import (
    AnomalyEvent,
    ApprovalDecision,
    Asset,
    DecisionType,
)


def make_asset(asset_id: str = "WD-001", safety_critical: bool | None = False) -> Asset:
    imaging = asset_id.startswith("IC-")
    return Asset(
        asset_id=asset_id,
        name="Imaging chiller" if imaging else "Wire-draw motor",
        asset_class="imaging_chiller" if imaging else "wire_draw_motor",
        criticality_tier=1 if asset_id == "IC-001" else 2,
        safety_critical=safety_critical,
        install_date=datetime(2020, 1, 1, tzinfo=UTC),
        site_id="CLINIC-1" if imaging else "PLANT-1",
        location="Test bay",
    )


def make_anomaly(asset_id: str, *, shadow: bool = False) -> AnomalyEvent:
    return AnomalyEvent(
        anomaly_id=f"AN-{asset_id}",
        asset_id=asset_id,
        detected_at=datetime(2026, 1, 1, tzinfo=UTC),
        anomaly_type="bearing_wear",
        severity=0.8,
        shadow=shadow,
        evidence={"features": {"vibration_rms": 4.1}},
    )


def test_workflow_waits_for_human_before_reserving_parts_and_is_idempotent() -> None:
    async def run() -> None:
        runner = WorkflowRunner()
        anomaly = make_anomaly("WD-001")
        asset = make_asset()
        pending = await runner.start(anomaly, asset)
        correlation_id = pending["correlation_id"]
        assert pending["status"] == "pending_approval"
        assert pending["approval_package"].diagnosis.candidates[0].verified
        assert runner.inventory.stock["BRG-101"] == 8
        assert await runner.start(anomaly, asset) is pending

        approved = await runner.decide(
            ApprovalDecision(
                correlation_id=correlation_id,
                decision=DecisionType.APPROVE,
                approver="operator-1",
            )
        )
        assert approved["status"] == "approved"
        assert runner.inventory.stock["BRG-101"] == 7
        assert runner.cmms.work_orders[correlation_id]["status"] == "APPROVED"
        assert (await runner.decide(approved["approval"])) is approved

    asyncio.run(run())


def test_rejection_does_not_reserve_and_escalation_keeps_work_pending() -> None:
    async def run() -> None:
        runner = WorkflowRunner()
        rejected = await runner.start(make_anomaly("WD-001"), make_asset())
        await runner.decide(
            ApprovalDecision(
                correlation_id=rejected["correlation_id"],
                decision=DecisionType.REJECT,
                approver="operator-1",
                reason="Evidence needs review",
            )
        )
        assert rejected["status"] == "rejected"
        assert runner.inventory.stock["BRG-101"] == 8

        escalated = await runner.start(make_anomaly("WD-002"), make_asset("WD-002"))
        original_tier = escalated["approval_package"].required_approver_tier
        await runner.decide(
            ApprovalDecision(
                correlation_id=escalated["correlation_id"],
                decision=DecisionType.ESCALATE,
                approver="operator-1",
                reason="Spend requires higher authority",
            )
        )
        assert escalated["status"] == "pending_approval"
        assert escalated["approval_package"].required_approver_tier == original_tier + 1
        assert runner.inventory.stock["BRG-101"] == 8

    asyncio.run(run())


def test_modify_approve_persists_structured_feedback_and_commits_parts() -> None:
    async def run() -> None:
        runner = WorkflowRunner()
        record = await runner.start(make_anomaly("WD-001"), make_asset())
        decision = ApprovalDecision(
            correlation_id=record["correlation_id"],
            decision=DecisionType.MODIFY_APPROVE,
            approver="operator-2",
            modifications={"priority": 1, "tasks": ["Verify the motor tag", "Inspect bearing"]},
        )
        await runner.decide(decision)
        assert record["status"] == "approved"
        assert record["work_order"].priority == 1
        assert runner.feedback[0]["modifications"] == decision.modifications
        assert runner.inventory.stock["BRG-101"] == 7

    asyncio.run(run())


def test_safety_critical_and_missing_classification_always_reach_human() -> None:
    async def run() -> None:
        for asset_id, classification, expected_reason in (
            ("IC-001", True, "safety_critical"),
            ("IC-002", None, "safety_classification_missing"),
        ):
            runner = WorkflowRunner()
            record = await runner.start(
                make_anomaly(asset_id), make_asset(asset_id, classification)
            )
            assert record["status"] == "pending_approval"
            assert expected_reason in record["approval_package"].reasons_for_hitl

    asyncio.run(run())


def test_adapter_failures_create_labeled_partial_approval_package() -> None:
    async def run() -> None:
        runner = WorkflowRunner()
        runner.cmms.cmms_down = True
        runner.inventory.inventory_down = True
        record = await runner.start(make_anomaly("WD-001"), make_asset())
        package = record["approval_package"]
        assert record["status"] == "pending_approval"
        assert record["cmms_queued"] is True
        assert package.partial is True
        assert package.parts.parts_tbc is True
        assert "partial_approval_package" in package.reasons_for_hitl

    asyncio.run(run())


def test_shadow_mode_diagnoses_without_work_order_or_approval() -> None:
    async def run() -> None:
        runner = WorkflowRunner()
        record = await runner.start(make_anomaly("WD-001", shadow=True), make_asset())
        assert record["status"] == "shadow"
        assert record["work_order"] is None
        assert record["correlation_id"] not in runner.pending
        assert not runner.cmms.work_orders

    asyncio.run(run())


def test_langgraph_pauses_and_resumes_when_dependency_is_installed() -> None:
    langgraph = pytest.importorskip("langgraph")
    del langgraph
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from app.agentweave.graph import build_graph

    handlers = {
        name: (lambda state: {})
        for name in ("diagnose", "work_order", "parts", "schedule", "partial_hitl")
    }
    handlers["diagnose"] = lambda state: {
        "status": "ready",
        "approval_package": {"correlation_id": "graph-1"},
    }
    handlers["finalize"] = lambda state: {"status": "complete"}
    graph = build_graph(handlers, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "graph-1"}}
    first = graph.invoke({"status": "new"}, config)
    assert first["__interrupt__"][0].value == {"correlation_id": "graph-1"}
    resumed = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert resumed["approval"] == {"decision": "approve"}
    assert resumed["status"] == "complete"