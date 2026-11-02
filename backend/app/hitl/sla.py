"""L7 approval SLA warnings and automatic escalation without auto-approval."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas.domain import ApprovalDecision, DecisionType


class SLAMonitor:
    def __init__(self, workflow_runner: Any, *, poll_seconds: float = 30.0) -> None:
        self.runner = workflow_runner
        self.poll_seconds = poll_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, correlation_id: str) -> None:
        task = self._tasks.get(correlation_id)
        if task is None or task.done():
            self._tasks[correlation_id] = asyncio.create_task(self._monitor(correlation_id))

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def check(
        self,
        correlation_id: str,
        *,
        now: datetime | None = None,
    ) -> str | None:
        record = self.runner.workflows.get(correlation_id)
        package = self.runner.pending.get(correlation_id)
        if record is None or package is None:
            return None
        current = now or datetime.now(UTC)
        tier = package.required_approver_tier
        sla_minutes = {
            1: self.runner.settings.sla_tier1_minutes,
            2: self.runner.settings.sla_tier2_minutes,
            3: self.runner.settings.sla_tier3_minutes,
        }[tier]
        started = record.get("approval_requested_at") or (
            package.sla_deadline - timedelta(minutes=sla_minutes)
        )
        warning_at = started + timedelta(minutes=sla_minutes * 0.75)
        if current >= warning_at and not record.get("sla_warning_sent", False):
            record["sla_warning_sent"] = True
            self._audit(
                record,
                "sla_warning",
                {"tier": tier, "deadline": package.sla_deadline.isoformat()},
            )
            self.runner._put_event(
                "sla_warning",
                {
                    "correlation_id": correlation_id,
                    "deadline": package.sla_deadline.isoformat(),
                    "tier": tier,
                },
            )
        if current >= package.sla_deadline:
            decision = ApprovalDecision(
                correlation_id=correlation_id,
                decision=DecisionType.ESCALATE,
                approver="sla-monitor",
                reason="Approval SLA breached; automatic escalation to the next tier.",
            )
            await self.runner.decide(decision)
            return "escalated"
        return "warning" if record.get("sla_warning_sent") else None

    async def _monitor(self, correlation_id: str) -> None:
        while correlation_id in self.runner.pending:
            await self.check(correlation_id)
            await asyncio.sleep(self.poll_seconds)

    def _audit(self, record: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        event = self.runner.ledger.append(
            record["correlation_id"], "sla-monitor", event_type, payload
        )
        self.runner._put_event("audit_event", event.model_dump(mode="json"))
