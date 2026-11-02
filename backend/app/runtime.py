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
        self.pipeline.open_work_orders_provider = self._open_work_orders

        async def on_anomaly(anomaly, asset) -> None:
            record = await self.workflow.start(anomaly, asset)
            if record["status"] == "pending_approval":
                self.approvals.sla.start(record["correlation_id"])

        self.pipeline.on_anomaly = on_anomaly

    def _open_work_orders(self, asset_id: str) -> list[dict]:
        return [
            work_order
            for work_order in self.workflow.cmms.work_orders.values()
            if work_order["assetnum"] == asset_id
            and work_order["status"] not in {"CLOSED", "REJECTED"}
        ]

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
        self.pipeline.pause()
        self.pipeline.start()


runtime = Runtime()
