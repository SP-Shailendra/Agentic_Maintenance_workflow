"""Process-local services for the fake/demo runtime and API integration."""

from app.agentweave.runner import WorkflowRunner
from app.datapulse.pipeline import PipelineRunner
from app.hitl.service import ApprovalService


class Runtime:
    def __init__(self) -> None:
        self.pipeline = PipelineRunner()
        self.workflow = WorkflowRunner()
        self.approvals = ApprovalService(self.workflow)
        self._wire_pipeline()

    def _wire_pipeline(self) -> None:
        async def on_anomaly(anomaly, asset) -> None:
            record = await self.workflow.start(anomaly, asset)
            if record["status"] == "pending_approval":
                self.approvals.sla.start(record["correlation_id"])

        self.pipeline.on_anomaly = on_anomaly

    async def close(self) -> None:
        await self.pipeline.stop()
        await self.approvals.sla.stop()

    async def reset(self) -> None:
        await self.approvals.sla.stop()
        await self.pipeline.stop()
        self.pipeline = PipelineRunner()
        self.workflow = WorkflowRunner()
        self.approvals = ApprovalService(self.workflow)
        self._wire_pipeline()


runtime = Runtime()