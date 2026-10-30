"""L1 deterministic sensor simulator for the five seeded assets."""

import asyncio
import json
import math
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.schemas.domain import Asset, MeasurementType, QualityFlag, TelemetryReading

BASELINES: dict[str, dict[MeasurementType, tuple[float, str]]] = {
    "wire_draw_motor": {
        MeasurementType.VIBRATION_RMS: (1.8, "mm/s"),
        MeasurementType.TEMPERATURE: (58.0, "degC"),
        MeasurementType.CURRENT: (12.0, "A"),
        MeasurementType.PRESSURE: (5.0, "bar"),
    },
    "testcell_generator": {
        MeasurementType.VIBRATION_RMS: (2.1, "mm/s"),
        MeasurementType.TEMPERATURE: (67.0, "degC"),
        MeasurementType.CURRENT: (34.0, "A"),
        MeasurementType.PRESSURE: (5.5, "bar"),
    },
    "imaging_chiller": {
        MeasurementType.VIBRATION_RMS: (1.2, "mm/s"),
        MeasurementType.TEMPERATURE: (6.0, "degC"),
        MeasurementType.CURRENT: (8.0, "A"),
        MeasurementType.PRESSURE: (7.0, "bar"),
    },
}


def load_assets(seed_path: Path | None = None) -> list[Asset]:
    path = seed_path or Path(__file__).resolve().parents[3] / "data" / "seed" / "assets.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Asset.model_validate(asset) for asset in payload]


class TelemetrySimulator:
    def __init__(
        self,
        assets: list[Asset] | None = None,
        *,
        seed: int = 17,
        tick_seconds: float = 5.0,
    ) -> None:
        self.assets = assets or load_assets()
        self.seed = seed
        self.random = random.Random(seed)
        self.tick_seconds = tick_seconds
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.scenario_started_ticks: dict[str, int] = {}
        self.scenario_durations: dict[str, int | None] = {}
        self.scenario_severities: dict[str, float] = {}
        self.scenario_seeds: dict[str, int | None] = {}
        self.scenario_ids: dict[str, str] = {}
        self.tick = 0
        self.paused = False
        self._stop = asyncio.Event()

    def inject(
        self,
        asset_id: str,
        scenario: str,
        *,
        severity: float = 0.8,
        duration_ticks: int | None = 120,
        seed: int | None = None,
    ) -> dict[str, str | int | float | None]:
        allowed = {
            "healthy",
            "bearing_wear",
            "overheat",
            "pressure_drop",
            "safety_critical_case",
            "unclassified_case",
        }
        if scenario not in allowed:
            raise ValueError(f"Unsupported scenario: {scenario}")
        if asset_id not in self.scenarios:
            raise KeyError(f"Unknown asset: {asset_id}")
        if not 0 <= severity <= 1:
            raise ValueError("severity must be between 0 and 1")
        if duration_ticks is not None and duration_ticks < 1:
            raise ValueError("duration_ticks must be at least 1")
        if seed is not None:
            self.random.seed(seed)
        self.scenarios[asset_id] = scenario
        if scenario == "healthy":
            self.clear(asset_id)
            return {"asset_id": asset_id, "scenario": "healthy", "scenario_id": None}
        scenario_id = f"SCN-{asset_id}-{self.tick}-{uuid4().hex[:8]}"
        self.scenario_started_ticks[asset_id] = self.tick
        self.scenario_durations[asset_id] = duration_ticks
        self.scenario_severities[asset_id] = severity
        self.scenario_seeds[asset_id] = seed
        self.scenario_ids[asset_id] = scenario_id
        return {
            "asset_id": asset_id,
            "scenario": scenario,
            "scenario_id": scenario_id,
            "severity": severity,
            "duration_ticks": duration_ticks,
            "seed": seed,
        }

    def clear(self, asset_id: str) -> bool:
        if asset_id not in self.scenarios:
            raise KeyError(f"Unknown asset: {asset_id}")
        was_active = self.scenarios[asset_id] != "healthy"
        self.scenarios[asset_id] = "healthy"
        self.scenario_started_ticks.pop(asset_id, None)
        self.scenario_durations.pop(asset_id, None)
        self.scenario_severities.pop(asset_id, None)
        self.scenario_seeds.pop(asset_id, None)
        self.scenario_ids.pop(asset_id, None)
        return was_active

    def active_scenarios(self) -> list[dict[str, str | int | float | None]]:
        active: list[dict[str, str | int | float | None]] = []
        for asset_id, scenario in self.scenarios.items():
            if scenario == "healthy":
                continue
            started_tick = self.scenario_started_ticks[asset_id]
            duration = self.scenario_durations[asset_id]
            elapsed = max(0, self.tick - started_tick)
            active.append(
                {
                    "asset_id": asset_id,
                    "scenario": scenario,
                    "scenario_id": self.scenario_ids[asset_id],
                    "severity": self.scenario_severities[asset_id],
                    "duration_ticks": duration,
                    "elapsed_ticks": elapsed,
                    "remaining_ticks": max(0, duration - elapsed) if duration is not None else None,
                    "seed": self.scenario_seeds[asset_id],
                }
            )
        return active

    def generate_tick(self, timestamp: datetime | None = None) -> list[TelemetryReading]:
        now = timestamp or datetime.now(UTC)
        readings: list[TelemetryReading] = []
        for asset_index, asset in enumerate(self.assets):
            duration = self.scenario_durations.get(asset.asset_id)
            started_tick = self.scenario_started_ticks.get(asset.asset_id, self.tick)
            if duration is not None and self.tick - started_tick >= duration:
                self.clear(asset.asset_id)
            scenario = self.scenarios[asset.asset_id]
            severity = self.scenario_severities.get(asset.asset_id, 0.0)
            if scenario == "safety_critical_case" and asset.asset_id != "IC-001":
                scenario = "bearing_wear"
            elif scenario == "unclassified_case" and asset.asset_id != "IC-002":
                scenario = "bearing_wear"
            for measurement_type, (baseline, unit) in BASELINES[asset.asset_class].items():
                seasonality = math.sin((self.tick + asset_index * 3) / 12) * baseline * 0.015
                noise = self.random.gauss(0, max(abs(baseline) * 0.012, 0.02))
                value = baseline + seasonality + noise
                scenario_start = self.scenario_started_ticks.get(asset.asset_id, self.tick)
                age = max(0, self.tick - scenario_start - 2)
                if scenario in {"bearing_wear", "safety_critical_case", "unclassified_case"}:
                    if measurement_type in {
                        MeasurementType.VIBRATION_RMS,
                        MeasurementType.TEMPERATURE,
                    }:
                        drift = 0.25 if measurement_type == MeasurementType.VIBRATION_RMS else 0.9
                        value += age * drift * severity
                elif scenario == "overheat":
                    if measurement_type in {MeasurementType.TEMPERATURE, MeasurementType.CURRENT}:
                        drift = 1.8 if measurement_type == MeasurementType.TEMPERATURE else 0.7
                        value += age * drift * severity
                elif scenario == "pressure_drop" and measurement_type == MeasurementType.PRESSURE:
                    value -= age * 0.3 * severity
                readings.append(
                    TelemetryReading(
                        asset_id=asset.asset_id,
                        sensor_id=f"{asset.asset_id}-{measurement_type.value}",
                        timestamp_utc=now,
                        measurement_type=measurement_type,
                        value=round(value, 4),
                        unit=unit,
                        quality_flag=QualityFlag.GOOD,
                    )
                )
        self.tick += 1
        for asset_id, duration in list(self.scenario_durations.items()):
            if (
                duration is not None
                and self.tick - self.scenario_started_ticks[asset_id] >= duration
            ):
                self.clear(asset_id)
        return readings

    async def stream(self) -> AsyncIterator[list[TelemetryReading]]:
        while not self._stop.is_set():
            if self.paused:
                await asyncio.sleep(min(self.tick_seconds, 0.1))
                continue
            yield self.generate_tick()
            await asyncio.sleep(self.tick_seconds)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def reset(self, *, seed: int | None = None) -> None:
        self.tick = 0
        self.seed = self.seed if seed is None else seed
        self.random.seed(self.seed)
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.scenario_started_ticks.clear()
        self.scenario_durations.clear()
        self.scenario_severities.clear()
        self.scenario_seeds.clear()
        self.scenario_ids.clear()
        self.paused = False