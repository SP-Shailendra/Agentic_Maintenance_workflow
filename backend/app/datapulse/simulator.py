"""L1 deterministic sensor simulator for the five seeded assets."""

import asyncio
import json
import math
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

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
        self.random = random.Random(seed)
        self.tick_seconds = tick_seconds
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.tick = 0
        self.paused = False
        self._stop = asyncio.Event()

    def inject(self, asset_id: str, scenario: str) -> None:
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
        self.scenarios[asset_id] = scenario

    def generate_tick(self, timestamp: datetime | None = None) -> list[TelemetryReading]:
        now = timestamp or datetime.now(UTC)
        readings: list[TelemetryReading] = []
        for asset_index, asset in enumerate(self.assets):
            scenario = self.scenarios[asset.asset_id]
            if scenario == "safety_critical_case" and asset.asset_id != "IC-001":
                scenario = "bearing_wear"
            elif scenario == "unclassified_case" and asset.asset_id != "IC-002":
                scenario = "bearing_wear"
            for measurement_type, (baseline, unit) in BASELINES[asset.asset_class].items():
                seasonality = math.sin((self.tick + asset_index * 3) / 12) * baseline * 0.015
                noise = self.random.gauss(0, max(abs(baseline) * 0.012, 0.02))
                value = baseline + seasonality + noise
                age = max(0, self.tick - 2)
                if scenario in {"bearing_wear", "safety_critical_case", "unclassified_case"}:
                    if measurement_type in {
                        MeasurementType.VIBRATION_RMS,
                        MeasurementType.TEMPERATURE,
                    }:
                        drift = 0.25 if measurement_type == MeasurementType.VIBRATION_RMS else 0.9
                        value += age * drift
                elif scenario == "overheat":
                    if measurement_type in {MeasurementType.TEMPERATURE, MeasurementType.CURRENT}:
                        drift = 1.8 if measurement_type == MeasurementType.TEMPERATURE else 0.7
                        value += age * drift
                elif scenario == "pressure_drop" and measurement_type == MeasurementType.PRESSURE:
                    value -= age * 0.3
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

    def reset(self) -> None:
        self.tick = 0
        self.random.seed(17)
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.paused = False