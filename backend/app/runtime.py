"""Process-local services for the fake/demo runtime and API integration."""

from app.agentweave.runner import WorkflowRunner
from app.datapulse.configuration import (
    AssetParameters,
    SimulatorConfiguration,
    load_simulator_configuration,
    write_simulator_configuration,
)
from app.datapulse.pipeline import PipelineRunner
from app.datapulse.simulator import TelemetrySimulator
from app.hitl.service import ApprovalService


class Runtime:
    def __init__(self) -> None:
        self.pipeline = PipelineRunner()
        self.workflow = WorkflowRunner()
        self.approvals = ApprovalService(self.workflow)
        self._simulator_parameter_undo: dict[str, AssetParameters] = {}
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

    async def reload_simulator_configuration(self) -> str:
        configuration = load_simulator_configuration()
        return await self.apply_simulator_configuration(configuration)

    async def apply_simulator_configuration(
        self,
        configuration: SimulatorConfiguration,
        *,
        persist: bool = False,
    ) -> str:
        if persist:
            write_simulator_configuration(configuration)
        previous = self.pipeline.simulator
        await self.pipeline.stop()
        simulator = TelemetrySimulator(
            assets=list(previous.assets),
            seed=configuration.master_seed,
            tick_seconds=configuration.tick_seconds,
            operating_cycle_ticks=configuration.operating_cycle_ticks,
            noise_scale=previous.noise_scale,
            configuration=configuration,
            speed=previous.clock.speed,
        )
        self.pipeline = PipelineRunner(simulator)
        self._wire_pipeline()
        self.pipeline.start()
        return configuration.config_hash

    async def reset(self) -> None:
        await self.approvals.sla.stop()
        await self.pipeline.stop()
        self._simulator_parameter_undo.clear()
        self.pipeline = PipelineRunner()
        self.workflow = WorkflowRunner()
        self.approvals = ApprovalService(self.workflow)
        self._wire_pipeline()
        self.pipeline.pause()
        self.pipeline.start()
