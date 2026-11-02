"""Run a fake-LLM approval loop and print the verified in-memory audit chain."""

import asyncio
from datetime import UTC, datetime

from app.agentweave.runner import WorkflowRunner
from app.datapulse.simulator import load_assets
from app.schemas.domain import AnomalyEvent, ApprovalDecision, DecisionType


async def main() -> None:
    runner = WorkflowRunner()
    asset = next(asset for asset in load_assets() if asset.asset_id == "IC-001")
    anomaly = AnomalyEvent(
        anomaly_id="AN-DEMO-001",
        asset_id=asset.asset_id,
        detected_at=datetime.now(UTC),
        anomaly_type="pressure_drop",
        severity=0.83,
        evidence={"pressure": {"rate_of_change": -1.4}},
    )
    record = await runner.start(anomaly, asset)
    package = record["approval_package"]
    print(f"Pending human approval: {package.correlation_id} / {package.asset_id}")
    print(f"Reasons: {', '.join(package.reasons_for_hitl)}")
    print(f"Work order: {package.work_order.summary if package.work_order else 'partial package'}")
    print("Parts reserved before decision: 0")

    await runner.decide(
        ApprovalDecision(
            correlation_id=package.correlation_id,
            decision=DecisionType.APPROVE,
            approver="demo-approver",
            reason="Reviewed synthetic demo package",
        )
    )
    print(f"Final status: {record['status']}")
    for event in runner.ledger.events:
        print(f"{event.seq:03d} {event.event_type} hash={event.hash[:12]}")
    ok, first_bad_seq = runner.ledger.verify()
    print(f"Audit chain verified: {ok}; first_bad_seq={first_bad_seq}")


if __name__ == "__main__":
    asyncio.run(main())
