"""L1 streaming runner connecting normalization, bus, features, and detectors."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.datapulse.bus import StreamBus
from app.datapulse.normalizer import TelemetryNormalizer
from app.datapulse.simulator import TelemetrySimulator
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
        self.spc = SPCDetector(
            baseline_size=max(30, self.simulator.operating_cycle_ticks),
            operating_cycle_ticks=self.simulator.operating_cycle_ticks,
        )
        spc_baselines, spc_profiles, isolation_forest_baselines = self._healthy_training_data()
        self.spc.fit(spc_baselines, phase_profiles=spc_profiles)
        self.ensemble = EnsembleDetector()
        self.isolation_forest = IsolationForestDetector()
        self.isolation_forest.train(isolation_forest_baselines)
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
            cycle_tick = self.simulator.tick - 1
            if normalized.scenario_id is not None:
                cycle_tick -= self.simulator.scenario_started_ticks.get(asset.asset_id, cycle_tick)
            spc_score = self.spc.score(
                asset.asset_class,
                normalized.measurement_type.value,
                normalized.asset_id,
                normalized.value,
                cycle_tick=cycle_tick,
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

    def _healthy_training_data(
        self,
    ) -> tuple[
        dict[tuple[str, str], list[float]],
        dict[tuple[str, str], list[float]],
        dict[tuple[str, str], list[float]],
    ]:
        simulator = self.simulator
        profile_simulator = TelemetrySimulator(
            assets=list(simulator.assets),
            seed=simulator.seed,
            tick_seconds=simulator.tick_seconds,
            operating_cycle_ticks=simulator.operating_cycle_ticks,
            noise_scale=0,
            configuration=simulator.configuration,
        )
        healthy_simulator = TelemetrySimulator(
            assets=list(simulator.assets),
            seed=simulator.seed + 1,
            tick_seconds=simulator.tick_seconds,
            operating_cycle_ticks=simulator.operating_cycle_ticks,
            noise_scale=simulator.noise_scale,
            configuration=simulator.configuration,
        )
        asset_classes = {asset.asset_id: asset.asset_class for asset in simulator.assets}
        spc_training: dict[tuple[str, str], list[float]] = defaultdict(list)
        spc_profiles: dict[tuple[str, str], list[float]] = defaultdict(list)
        isolation_forest_training: dict[tuple[str, str], list[float]] = defaultdict(list)
        training_ticks = max(8 * simulator.operating_cycle_ticks, self.spc.baseline_size)
        for _ in range(training_ticks):
            for reading in profile_simulator.generate_tick():
                spc_profiles[(reading.asset_id, reading.measurement_type.value)].append(
                    reading.value
                )
        for _tick in range(training_ticks):
            for reading in healthy_simulator.generate_tick():
                measurement = reading.measurement_type.value
                spc_training[(reading.asset_id, measurement)].append(reading.value)
                isolation_forest_training[(asset_classes[reading.asset_id], measurement)].append(
                    reading.value
                )
        return dict(spc_training), dict(spc_profiles), dict(isolation_forest_training)

    async def _run(self) -> None:
        while True:
            if self.simulator.paused:
                await asyncio.sleep(min(self.simulator.clock.sleep_seconds, 0.1))
                continue
            await self.process_tick()
            await asyncio.sleep(self.simulator.clock.sleep_seconds)

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
