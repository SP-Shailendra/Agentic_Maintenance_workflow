"""L1 deterministic sensor simulator for the five seeded assets."""

import asyncio
import hashlib
import json
import math
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
        operating_cycle_ticks: int = 120,
        noise_scale: float = 1.0,
    ) -> None:
        self.assets = assets or load_assets()
        self.seed = seed
        self._random_by_asset = {
            asset.asset_id: random.Random(self._asset_seed(seed, asset.asset_id))
            for asset in self.assets
        }
        self.tick_seconds = tick_seconds
        self.operating_cycle_ticks = max(1, operating_cycle_ticks)
        if noise_scale < 0:
            raise ValueError("noise_scale must be non-negative")
        self.noise_scale = noise_scale
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.scenario_started_ticks: dict[str, int] = {}
        self.scenario_durations: dict[str, int | None] = {}
        self.scenario_severities: dict[str, float] = {}
        self.scenario_seeds: dict[str, int | None] = {}
        self.scenario_ids: dict[str, str] = {}
        self.scenario_measurements: dict[str, str | None] = {}
        self.scenario_recovery_ticks: dict[str, int | None] = {}
        self.scenario_counter = 0
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
        measurement_type: str | None = None,
        recovery_after_ticks: int | None = None,
    ) -> dict[str, str | int | float | None]:
        allowed = {
            "healthy",
            "bearing_wear",
            "overheat",
            "pressure_drop",
            "safety_critical_case",
            "unclassified_case",
            "intermittent_bearing",
            "recovering_bearing_wear",
            "sensor_dropout",
            "bad_quality",
            "out_of_order",
        }
        if scenario not in allowed:
            raise ValueError(f"Unsupported scenario: {scenario}")
        if asset_id not in self.scenarios:
            raise KeyError(f"Unknown asset: {asset_id}")
        if not 0 <= severity <= 1:
            raise ValueError("severity must be between 0 and 1")
        if duration_ticks is not None and duration_ticks < 1:
            raise ValueError("duration_ticks must be at least 1")
        supported_measurements = {measurement.value for measurement in MeasurementType}
        if measurement_type is not None and measurement_type not in supported_measurements:
            raise ValueError(f"Unsupported measurement_type: {measurement_type}")
        if recovery_after_ticks is not None and recovery_after_ticks < 0:
            raise ValueError("recovery_after_ticks must be non-negative")
        if (
            recovery_after_ticks is not None
            and duration_ticks is not None
            and recovery_after_ticks >= duration_ticks
        ):
            raise ValueError("recovery_after_ticks must be less than duration_ticks")
        if scenario == "recovering_bearing_wear" and recovery_after_ticks is None:
            recovery_after_ticks = max(1, duration_ticks // 2) if duration_ticks is not None else 40
        if seed is not None:
            self._random_by_asset[asset_id].seed(seed)
        self.scenarios[asset_id] = scenario
        self.scenario_counter += 1
        scenario_id = f"SCN-{asset_id}-{self.tick}-{self.scenario_counter:04d}"
        self.scenario_started_ticks[asset_id] = self.tick
        self.scenario_durations[asset_id] = duration_ticks
        self.scenario_severities[asset_id] = severity
        self.scenario_seeds[asset_id] = seed
        self.scenario_ids[asset_id] = scenario_id
        self.scenario_measurements[asset_id] = measurement_type
        self.scenario_recovery_ticks[asset_id] = recovery_after_ticks
        return {
            "asset_id": asset_id,
            "scenario": scenario,
            "scenario_id": scenario_id,
            "start_tick": self.tick,
            "severity": severity,
            "duration_ticks": duration_ticks,
            "seed": seed,
            "measurement_type": measurement_type,
            "recovery_after_ticks": recovery_after_ticks,
        }

    def clear(self, asset_id: str) -> bool:
        if asset_id not in self.scenarios:
            raise KeyError(f"Unknown asset: {asset_id}")
        was_active = asset_id in self.scenario_ids
        self.scenarios[asset_id] = "healthy"
        self.scenario_started_ticks.pop(asset_id, None)
        self.scenario_durations.pop(asset_id, None)
        self.scenario_severities.pop(asset_id, None)
        self.scenario_seeds.pop(asset_id, None)
        self.scenario_ids.pop(asset_id, None)
        self.scenario_measurements.pop(asset_id, None)
        self.scenario_recovery_ticks.pop(asset_id, None)
        return was_active

    def active_scenarios(self) -> list[dict[str, str | int | float | None]]:
        active: list[dict[str, str | int | float | None]] = []
        for asset_id, scenario in self.scenarios.items():
            if asset_id not in self.scenario_ids:
                continue
            started_tick = self.scenario_started_ticks[asset_id]
            duration = self.scenario_durations[asset_id]
            elapsed = max(0, self.tick - started_tick)
            active.append(
                {
                    "asset_id": asset_id,
                    "scenario": scenario,
                    "scenario_id": self.scenario_ids[asset_id],
                    "start_tick": started_tick,
                    "severity": self.scenario_severities[asset_id],
                    "duration_ticks": duration,
                    "elapsed_ticks": elapsed,
                    "remaining_ticks": max(0, duration - elapsed) if duration is not None else None,
                    "seed": self.scenario_seeds[asset_id],
                    "measurement_type": self.scenario_measurements[asset_id],
                    "recovery_after_ticks": self.scenario_recovery_ticks[asset_id],
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
            scenario_id = self.scenario_ids.get(asset.asset_id)
            if scenario == "safety_critical_case" and asset.asset_id != "IC-001":
                scenario = "healthy"
            elif scenario == "unclassified_case" and asset.asset_id != "IC-002":
                scenario = "healthy"
            scenario_start = self.scenario_started_ticks.get(asset.asset_id, self.tick)
            elapsed = max(0, self.tick - scenario_start)
            cycle_tick = elapsed if scenario_id is not None else self.tick
            cycle_phase = 2 * math.pi * cycle_tick / self.operating_cycle_ticks
            operating_load = 0.65 + 0.35 * ((1 + math.sin(cycle_phase + asset_index * 0.6)) / 2)
            for measurement_type, (baseline, unit) in BASELINES[asset.asset_class].items():
                if scenario == "sensor_dropout" and measurement_type.value == (
                    self.scenario_measurements.get(asset.asset_id) or "vibration_rms"
                ):
                    continue
                cycle_fraction = (operating_load - 0.65) / 0.35
                cycle_effect = {
                    MeasurementType.VIBRATION_RMS: baseline * 0.06,
                    MeasurementType.TEMPERATURE: baseline * 0.04,
                    MeasurementType.CURRENT: baseline * 0.20,
                    MeasurementType.PRESSURE: baseline * 0.015,
                }[measurement_type]
                seasonality = math.sin((cycle_tick + asset_index * 3) / 12) * baseline * 0.015
                noise = self._random_by_asset[asset.asset_id].gauss(
                    0,
                    max(abs(baseline) * 0.012, 0.02) * self.noise_scale,
                )
                value = baseline + cycle_effect * cycle_fraction + seasonality + noise
                age = max(0, elapsed - 2)
                fault_severity = severity
                if scenario == "intermittent_bearing" and elapsed % 8 >= 3:
                    fault_severity = 0.0
                recovery_after = self.scenario_recovery_ticks.get(asset.asset_id)
                if recovery_after is not None and elapsed >= recovery_after:
                    recovery_length = max(1, (duration or recovery_after + 20) - recovery_after)
                    fault_severity *= max(0.0, 1 - (elapsed - recovery_after) / recovery_length)
                if scenario in {
                    "bearing_wear",
                    "safety_critical_case",
                    "unclassified_case",
                    "intermittent_bearing",
                    "recovering_bearing_wear",
                }:
                    if measurement_type in {
                        MeasurementType.VIBRATION_RMS,
                        MeasurementType.TEMPERATURE,
                    }:
                        drift = 0.25 if measurement_type == MeasurementType.VIBRATION_RMS else 0.9
                        value += age * drift * fault_severity
                elif scenario == "overheat":
                    if measurement_type in {MeasurementType.TEMPERATURE, MeasurementType.CURRENT}:
                        drift = 1.8 if measurement_type == MeasurementType.TEMPERATURE else 0.7
                        value += age * drift * fault_severity
                elif scenario == "pressure_drop" and measurement_type == MeasurementType.PRESSURE:
                    value -= age * 0.3 * fault_severity
                timestamp_utc = now
                if scenario == "out_of_order" and measurement_type.value == (
                    self.scenario_measurements.get(asset.asset_id) or "vibration_rms"
                ):
                    skew_direction = 1 if self.tick % 2 == 0 else -1
                    timestamp_utc = now + timedelta(seconds=self.tick_seconds * 2 * skew_direction)
                quality_flag = (
                    QualityFlag.BAD
                    if scenario == "bad_quality"
                    and measurement_type.value
                    == (self.scenario_measurements.get(asset.asset_id) or "vibration_rms")
                    else QualityFlag.GOOD
                )
                readings.append(
                    TelemetryReading(
                        asset_id=asset.asset_id,
                        sensor_id=f"{asset.asset_id}-{measurement_type.value}",
                        scenario_id=scenario_id,
                        timestamp_utc=timestamp_utc,
                        measurement_type=measurement_type,
                        value=round(value, 4),
                        unit=unit,
                        quality_flag=quality_flag,
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
        self._random_by_asset = {
            asset.asset_id: random.Random(self._asset_seed(self.seed, asset.asset_id))
            for asset in self.assets
        }
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.scenario_started_ticks.clear()
        self.scenario_durations.clear()
        self.scenario_severities.clear()
        self.scenario_seeds.clear()
        self.scenario_ids.clear()
        self.scenario_measurements.clear()
        self.scenario_recovery_ticks.clear()
        self.scenario_counter = 0
        self.paused = False

    @staticmethod
    def _asset_seed(seed: int, asset_id: str) -> int:
        digest = hashlib.blake2b(f"{seed}:{asset_id}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big")
