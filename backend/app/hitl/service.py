"""L7 orchestration facade joining decisions, SLA timers, and notifications."""

from app.agentweave.runner import WorkflowRunner
from app.hitl.notifier import ConsoleNotifier, Notifier
from app.hitl.sla import SLAMonitor
from app.schemas.domain import ApprovalDecision


class ApprovalService:
    def __init__(self, runner: WorkflowRunner, notifier: Notifier | None = None) -> None:
        self.runner = runner
        self.notifier = notifier or ConsoleNotifier()
        self.sla = SLAMonitor(runner)

    async def submit(self, decision: ApprovalDecision) -> dict:
        result = await self.runner.decide(decision)
        await self.notifier.notify(
            "approval_decided",
            {
                "correlation_id": decision.correlation_id,
                "decision": decision.decision.value,
                "approver": decision.approver,
            },
        )
        return result