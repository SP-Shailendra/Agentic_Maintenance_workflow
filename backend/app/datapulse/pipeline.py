"""L1 streaming runner connecting normalization, bus, features, and detectors."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.datapulse.bus import StreamBus
from app.datapulse.normalizer import TelemetryNormalizer
from app.datapulse.simulator import BASELINES, TelemetrySimulator
from app.datapulse_ai.detection.ensemble import EnsembleDetector
from app.datapulse_ai.detection.isolation_forest import IsolationForestDetector
from app.datapulse_ai.detection.spc import SPCDetector
from app.datapulse_ai.detection.suppression import AlertSuppressor
from app.datapulse_ai.features import FeatureEngine
from app.schemas.domain import AnomalyEvent, Asset, TelemetryReading


class PipelineRunner:
    def __init__(self, simulator: TelemetrySimulator | None = None) -> None:
        self.simulator = simulator or TelemetrySimulator()
        self.normalizer = TelemetryNormalizer()
        self.bus = StreamBus()
        self.features = FeatureEngine()
        self.spc = SPCDetector()
        healthy_baselines = self._healthy_training_data()
        self.spc.fit(healthy_baselines)
        self.ensemble = EnsembleDetector()
        self.isolation_forest = IsolationForestDetector()
        self.isolation_forest.train(healthy_baselines)
        self.suppressor = AlertSuppressor()
        self.readings: list[TelemetryReading] = []
        self.anomalies: list[AnomalyEvent] = []
        self.suppressed: list[dict[str, Any]] = []
        self.scenario_runs: list[dict[str, Any]] = []
        self.health: dict[str, float] = {asset.asset_id: 100.0 for asset in self.simulator.assets}
        self._task: asyncio.Task[None] | None = None
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.on_anomaly: Callable[[AnomalyEvent, Asset], Awaitable[None]] | None = None
        self.open_work_orders_provider: Callable[[str], list[dict[str, Any]]] = lambda _: []

    async def process_tick(self) -> list[AnomalyEvent]:
        tick_anomalies: list[AnomalyEvent] = []
        latest: dict[str, dict[str, dict[str, float]]] = {}
        latest_features: dict[str, dict[str, Any]] = {}
        latest_scenario_ids: dict[str, str | None] = {}
        for reading in self.simulator.generate_tick():
            normalized = self.normalizer.normalize(reading)
            if normalized is None:
                continue
            self.readings.append(normalized)
            await self.bus.publish(normalized)
            normalized = await self.bus.receive()
            asset = next(
                asset for asset in self.simulator.assets if asset.asset_id == reading.asset_id
            )
            feature = self.features.add(
                normalized,
                context={
                    "asset_class": asset.asset_class,
                    "criticality_tier": asset.criticality_tier,
                    "days_since_last_pm": asset.days_since_last_pm,
                    "open_work_orders": len(self.open_work_orders_provider(asset.asset_id)),
                },
            )
            latest_features[asset.asset_id] = feature
            latest_scenario_ids[asset.asset_id] = normalized.scenario_id
            spc_score = self.spc.score(
                asset.asset_class,
                normalized.measurement_type.value,
                normalized.asset_id,
                normalized.value,
            )
            latest.setdefault(normalized.asset_id, {})[normalized.measurement_type.value] = {
                "spc": spc_score,
                "isolation_forest": self.isolation_forest.score(
                    asset.asset_class,
                    normalized.measurement_type.value,
                    normalized.value,
                ),
            }
            await self.events.put({"type": "telemetry", "data": normalized.model_dump(mode="json")})
        for asset_id, measurements in latest.items():
            detection = self.ensemble.combine(measurements)
            self.health[asset_id] = round(max(0, 100 - detection.score * 100), 1)
            if not detection.triggered:
                continue
            suppressed, reason = self.suppressor.should_suppress(
                asset_id, detection.anomaly_type, datetime.now(UTC)
            )
            if suppressed:
                entry = {
                    "asset_id": asset_id,
                    "anomaly_type": detection.anomaly_type,
                    "reason": reason,
                }
                self.suppressed.append(entry)
                await self.events.put({"type": "suppressed", "data": entry})
                continue
            anomaly = AnomalyEvent(
                anomaly_id=f"AN-{len(self.anomalies) + 1:06d}",
                asset_id=asset_id,
                detected_at=datetime.now(UTC),
                detected_at_tick=max(0, self.simulator.tick - 1),
                scenario_id=latest_scenario_ids.get(asset_id),
                anomaly_type=detection.anomaly_type,
                severity=detection.score,
                shadow=False,
                evidence={"features": latest_features[asset_id], "ensemble": detection.breakdown},
            )
            self.anomalies.append(anomaly)
            tick_anomalies.append(anomaly)
            await self.events.put({"type": "anomaly", "data": anomaly.model_dump(mode="json")})
            if self.on_anomaly is not None:
                asset = next(item for item in self.simulator.assets if item.asset_id == asset_id)
                await self.on_anomaly(anomaly, asset)
        active_scenario_ids = {
            scenario["scenario_id"] for scenario in self.simulator.active_scenarios()
        }
        for run in self.scenario_runs:
            if run["status"] == "active" and run["scenario_id"] not in active_scenario_ids:
                run["status"] = "completed"
                run["end_tick"] = self.simulator.tick
                run["end_time_utc"] = datetime.now(UTC).isoformat()
        return tick_anomalies

    @staticmethod
    def _healthy_training_data() -> dict[tuple[str, str], list[float]]:
        training: dict[tuple[str, str], list[float]] = {}
        for asset_class, measurements in BASELINES.items():
            for measurement_type, (baseline, _) in measurements.items():
                spread = max(abs(baseline) * 0.015, 0.02)
                training[(asset_class, measurement_type.value)] = [
                    baseline + ((index % 11) - 5) * spread / 5 for index in range(100)
                ]
        return training

    async def _run(self) -> None:
        while True:
            if self.simulator.paused:
                await asyncio.sleep(min(self.simulator.tick_seconds, 0.1))
                continue
            await self.process_tick()
            await asyncio.sleep(self.simulator.tick_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def pause(self) -> None:
        self.simulator.pause()

    def resume(self) -> None:
        self.simulator.resume()

    def reset(self) -> None:
        self.simulator.reset()
        self.readings.clear()
        self.anomalies.clear()
        self.suppressed.clear()