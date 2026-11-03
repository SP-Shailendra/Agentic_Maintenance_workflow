"""L1 deterministic sensor simulator for the five seeded assets."""

import asyncio
import csv
import json
import math
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np

from app.datapulse.configuration import (
    AssetParameters,
    ScenarioProfile,
    SimulatorConfiguration,
    load_simulator_configuration,
)
from app.datapulse.vibration import synthesize_window
from app.schemas.domain import Asset, MeasurementType, QualityFlag, TelemetryReading

SIMULATION_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
OperatingState = Literal["stopped", "starting", "running", "idle", "stopping"]


class SimClock:
    def __init__(
        self,
        tick_seconds: float,
        *,
        t0: datetime | None = None,
        speed: float | Literal["max"] = 1,
    ) -> None:
        self.t0 = t0 or SIMULATION_EPOCH
        self.tick_seconds = tick_seconds
        self.tick = 0
        self.last_timestamp = self.t0
        self.set_speed(speed)

    @property
    def now(self) -> datetime:
        return self.t0 + timedelta(seconds=self.tick * self.tick_seconds)

    @property
    def sleep_seconds(self) -> float:
        return 0 if self.speed == "max" else self.tick_seconds / self.speed

    def set_speed(self, speed: float | Literal["max"]) -> None:
        if speed != "max" and speed not in {1, 10, 100}:
            raise ValueError("speed must be 1, 10, 100, or 'max'")
        self.speed = speed

    def advance(self) -> datetime:
        self.last_timestamp = self.now
        self.tick += 1
        return self.last_timestamp

    def reset(self, *, t0: datetime | None = None) -> None:
        if t0 is not None:
            self.t0 = t0
        self.tick = 0
        self.last_timestamp = self.t0


def _baseline_view(
    config: SimulatorConfiguration,
) -> dict[str, dict[MeasurementType, tuple[float, str]]]:
    return {
        asset_class: {
            MeasurementType(measurement): (signal.baseline, signal.unit)
            for measurement, signal in profile.signals.items()
        }
        for asset_class, profile in config.asset_classes.items()
    }


BASELINES = _baseline_view(load_simulator_configuration())


def load_assets(seed_path: Path | None = None) -> list[Asset]:
    path = seed_path or Path(__file__).resolve().parents[3] / "data" / "seed" / "assets.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Asset.model_validate(asset) for asset in payload]


class TelemetrySimulator:
    def __init__(
        self,
        assets: list[Asset] | None = None,
        *,
        seed: int | None = None,
        tick_seconds: float | None = None,
        operating_cycle_ticks: int | None = None,
        noise_scale: float = 1.0,
        configuration: SimulatorConfiguration | None = None,
        config_dir: Path | None = None,
        speed: float | Literal["max"] = 1,
    ) -> None:
        self.assets = assets or load_assets()
        self.configuration = configuration or load_simulator_configuration(config_dir)
        self.seed = self.configuration.master_seed if seed is None else seed
        self.tick_seconds = (
            self.configuration.tick_seconds if tick_seconds is None else tick_seconds
        )
        self.operating_cycle_ticks = max(
            1,
            self.configuration.operating_cycle_ticks
            if operating_cycle_ticks is None
            else operating_cycle_ticks,
        )
        if noise_scale < 0:
            raise ValueError("noise_scale must be non-negative")
        self.noise_scale = noise_scale
        self.clock = SimClock(self.tick_seconds, speed=speed)
        self.config_hash = self.configuration.config_hash
        self._rngs = self._spawn_rngs(self.seed)
        self._load_replay = self._load_csv_replay()
        self._noise_state: dict[tuple[str, str], float] = {}
        self._thermal_state = {
            (asset.asset_id, MeasurementType.TEMPERATURE.value): self._initial_temperature(asset)
            for asset in self.assets
        }
        self._sensor_state: dict[tuple[str, str], float] = {}
        self._load_state = {
            asset.asset_id: self.configuration.load_profile.base for asset in self.assets
        }
        self.process_states: dict[str, OperatingState] = {
            asset.asset_id: "running" for asset in self.assets
        }
        self._process_state_started = {asset.asset_id: 0 for asset in self.assets}
        self._scenario_previous_state: dict[str, OperatingState] = {}
        self.health: dict[tuple[str, str], float] = {}
        self._transport_pending: deque[tuple[int, TelemetryReading]] = deque(
            maxlen=self.configuration.transport.buffer_capacity
        )
        self.transport_dropped = 0
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.scenario_started_ticks: dict[str, int] = {}
        self.scenario_durations: dict[str, int | None] = {}
        self.scenario_severities: dict[str, float] = {}
        self.scenario_seeds: dict[str, int | None] = {}
        self.scenario_ids: dict[str, str] = {}
        self.scenario_measurements: dict[str, str | None] = {}
        self.scenario_recovery_ticks: dict[str, int | None] = {}
        self.scenario_counter = 0
        self.paused = False
        self._stop = asyncio.Event()

    @property
    def tick(self) -> int:
        return self.clock.tick

    @tick.setter
    def tick(self, value: int) -> None:
        self.clock.tick = value

    @property
    def master_seed(self) -> int:
        return self.seed

    def _asset_profile(self, asset: Asset):
        try:
            return self.configuration.asset_classes[asset.asset_class]
        except KeyError as error:
            raise ValueError(
                f"No simulator profile for asset class: {asset.asset_class}"
            ) from error

    def _asset_parameters(self, asset: Asset) -> AssetParameters:
        return self.configuration.asset_parameters.get(asset.asset_id, AssetParameters())

    def _initial_temperature(self, asset: Asset) -> float:
        signal = self._asset_profile(asset).signals[MeasurementType.TEMPERATURE.value]
        parameters = self._asset_parameters(asset)
        baseline = signal.baseline * parameters.baseline_scale
        load_profile = self.configuration.load_profile
        asset_index = self.assets.index(asset)
        state = baseline + baseline * signal.load_fraction * parameters.load_scale * 0.5
        alpha = (
            1.0
            if self.tick_seconds <= 0
            else 1
            - math.exp(
                -self.tick_seconds
                / (
                    self._asset_profile(asset).thermal_time_constant_seconds
                    * parameters.thermal_time_constant_scale
                )
            )
        )
        warmup_ticks = 20 * self.operating_cycle_ticks
        for tick in range(warmup_ticks):
            if load_profile.source == "sine":
                phase = 2 * math.pi * tick / self.operating_cycle_ticks
                phase += asset_index * load_profile.phase_offset_per_asset
                load = load_profile.base + load_profile.amplitude * (1 + math.sin(phase)) / 2
            elif load_profile.source == "schedule" and load_profile.schedule:
                load = load_profile.schedule[tick % len(load_profile.schedule)]
            elif load_profile.source == "csv_replay" and self._load_replay:
                load = self._load_replay[tick % len(self._load_replay)]
            else:
                load = load_profile.base
            nominal_load = load_profile.base + load_profile.amplitude * 0.5
            target = self._asset_profile(asset).ambient_temperature_c + (
                baseline - self._asset_profile(asset).ambient_temperature_c
            ) * (load / max(nominal_load, 1e-9))
            state += alpha * (target - state)
        return state

    def set_operating_state(
        self,
        asset_id: str,
        state: Literal["stopped", "starting", "running", "idle", "stopping"],
    ) -> str:
        if asset_id not in self.process_states:
            raise KeyError(f"Unknown asset: {asset_id}")
        if state == "running" and self.process_states[asset_id] in {"stopped", "idle"}:
            state = "starting"
        self.process_states[asset_id] = state
        self._process_state_started[asset_id] = self.tick
        return state

    def _current_process_state(self, asset: Asset) -> str:
        state = self.process_states[asset.asset_id]
        startup_ticks = self._asset_profile(asset).startup_ticks
        elapsed = self.tick - self._process_state_started[asset.asset_id]
        if state == "starting" and elapsed >= startup_ticks:
            state = "running"
        elif state == "stopping" and elapsed >= startup_ticks:
            state = "stopped"
        self.process_states[asset.asset_id] = state
        return state

    def _spawn_rngs(self, seed: int) -> dict[tuple[str, str, str], np.random.Generator]:
        keys = [
            (asset_id, sensor, source)
            for asset_id in sorted(asset.asset_id for asset in self.assets)
            for sensor in sorted(self.configuration.sensors)
            for source in ("noise", "timestamp", "load", "transport", "waveform")
        ]
        keys.extend((asset.asset_id, "load", "load") for asset in self.assets)
        children = np.random.SeedSequence(seed).spawn(len(keys))
        return {
            key: np.random.default_rng(child) for key, child in zip(keys, children, strict=True)
        }

    def _reseed_asset(self, asset_id: str, seed: int) -> None:
        keys = [
            (asset_id, sensor, source)
            for sensor in sorted(self.configuration.sensors)
            for source in ("noise", "timestamp", "load", "transport", "waveform")
        ]
        keys.append((asset_id, "load", "load"))
        children = np.random.SeedSequence(seed).spawn(len(keys))
        for key, child in zip(keys, children, strict=True):
            self._rngs[key] = np.random.default_rng(child)
        self._noise_state = {
            key: value for key, value in self._noise_state.items() if key[0] != asset_id
        }

    def _load_csv_replay(self) -> list[float] | None:
        path = self.configuration.load_profile.csv_replay_path
        if self.configuration.load_profile.source != "csv_replay" or path is None:
            return None
        replay_path = Path(path)
        if not replay_path.is_absolute():
            replay_path = Path(__file__).resolve().parents[3] / replay_path
        with replay_path.open(newline="", encoding="utf-8") as source:
            values = [float(row[0]) for row in csv.reader(source) if row]
        if not values or any(not 0 <= value <= 1 for value in values):
            raise ValueError("CSV load replay must contain values between 0 and 1")
        return values

    def _operating_load(self, asset_id: str, asset_index: int) -> float:
        profile = self.configuration.load_profile
        if profile.source == "sine":
            phase = 2 * math.pi * self.tick / self.operating_cycle_ticks
            phase += asset_index * profile.phase_offset_per_asset
            fraction = (1 + math.sin(phase)) / 2
            return min(1.0, max(0.0, profile.base + profile.amplitude * fraction))
        if profile.source == "schedule":
            schedule = profile.schedule or []
            return schedule[self.tick % len(schedule)]
        if profile.source == "random_walk":
            key = (asset_id, "load", "load")
            value = self._load_state[asset_id] + float(self._rngs[key].normal(0, 0.02))
            self._load_state[asset_id] = min(1.0, max(0.0, value))
            return self._load_state[asset_id]
        if profile.source == "csv_replay" and self._load_replay:
            return self._load_replay[self.tick % len(self._load_replay)]
        raise ValueError(f"Unsupported load source: {profile.source}")

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
        if scenario not in self.configuration.scenarios:
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
            self._reseed_asset(asset_id, seed)
        scenario_process_state = self.configuration.scenarios[scenario].process_state
        if scenario_process_state is not None:
            self._scenario_previous_state[asset_id] = self.process_states[asset_id]
            self.set_operating_state(asset_id, scenario_process_state)
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
            "master_seed": self.master_seed,
            "config_hash": self.config_hash,
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
        previous_state = self._scenario_previous_state.pop(asset_id, None)
        if previous_state is not None:
            self.set_operating_state(asset_id, previous_state)
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
                    "master_seed": self.master_seed,
                    "config_hash": self.config_hash,
                }
            )
        return active

    @staticmethod
    def _degradation(profile: ScenarioProfile, elapsed: int) -> float:
        age = max(0, elapsed - profile.onset_delay_ticks)
        if profile.curve == "exponential":
            return math.expm1(min(50, profile.curve_rate * age)) / profile.curve_rate
        if profile.curve == "stepwise":
            return float(age // profile.curve_period_ticks * profile.curve_period_ticks)
        if profile.curve == "sigmoid":
            return 2 / profile.curve_rate * math.tanh(profile.curve_rate * age / 2)
        if profile.curve == "bursty":
            return float(age if age % profile.curve_period_ticks == 0 else 0)
        if profile.curve == "weibull":
            return (profile.curve_rate * age) ** profile.curve_shape / profile.curve_rate
        return float(age)

    def _fault_effect(self, name: str, measurement: str, elapsed: int) -> float:
        profile = self.configuration.scenarios[name]
        return self._degradation(profile, elapsed) * profile.effects_per_tick.get(
            measurement, 0.0
        ) + sum(
            self._fault_effect(component, measurement, elapsed) for component in profile.components
        )

    def _transport(self, readings: list[TelemetryReading]) -> list[TelemetryReading]:
        profile = self.configuration.transport
        for reading in readings:
            rng = self._rngs[(reading.asset_id, reading.measurement_type.value, "transport")]
            if rng.random() < profile.loss_probability:
                self.transport_dropped += 1
                continue
            delivery_tick = self.tick + profile.latency_ticks
            if profile.jitter_ticks:
                delivery_tick += int(rng.integers(0, profile.jitter_ticks + 1))
            if rng.random() < profile.out_of_order_probability:
                delivery_tick += 2
            reading = reading.model_copy(
                update={
                    "timestamp_utc": reading.timestamp_utc
                    + timedelta(seconds=profile.clock_skew_seconds)
                }
            )
            copies = 2 if rng.random() < profile.duplicate_probability else 1
            for _copy in range(copies):
                if len(self._transport_pending) == self._transport_pending.maxlen:
                    self.transport_dropped += 1
                self._transport_pending.append((delivery_tick, reading))
        if (
            profile.outage_start_tick
            <= self.tick
            < (profile.outage_start_tick + profile.outage_duration_ticks)
        ):
            return []
        delivered: list[TelemetryReading] = []
        for _pending in range(len(self._transport_pending)):
            delivery_tick, reading = self._transport_pending.popleft()
            if delivery_tick <= self.tick:
                delivered.append(reading)
            else:
                self._transport_pending.append((delivery_tick, reading))
        return delivered

    def vibration_window(self, asset_id: str, severity: float = 0):
        if asset_id not in self.scenarios:
            raise KeyError(f"Unknown asset: {asset_id}")
        if not 0 <= severity <= 1:
            raise ValueError("severity must be between zero and one")
        return synthesize_window(
            self.configuration.vibration,
            self._rngs[(asset_id, "vibration_rms", "waveform")],
            severity,
        )

    def generate_tick(self, timestamp: datetime | None = None) -> list[TelemetryReading]:
        now = timestamp if timestamp is not None else self.clock.now
        self.clock.last_timestamp = now
        readings: list[TelemetryReading] = []
        for asset_index, asset in enumerate(self.assets):
            duration = self.scenario_durations.get(asset.asset_id)
            started_tick = self.scenario_started_ticks.get(asset.asset_id, self.tick)
            if duration is not None and self.tick - started_tick >= duration:
                self.clear(asset.asset_id)
            scenario = self.scenarios[asset.asset_id]
            scenario_profile = self.configuration.scenarios[scenario]
            asset_profile = self._asset_profile(asset)
            severity = self.scenario_severities.get(asset.asset_id, 0.0)
            scenario_id = self.scenario_ids.get(asset.asset_id)
            scenario_start = self.scenario_started_ticks.get(asset.asset_id, self.tick)
            elapsed = max(0, self.tick - scenario_start)
            cycle_tick = elapsed if scenario_id is not None else self.tick
            process_state = self._current_process_state(asset)
            operating_load = self._operating_load(asset.asset_id, asset_index)
            if process_state in {"stopped", "stopping"}:
                operating_load = 0.0
            elif process_state == "idle":
                operating_load = min(operating_load, 0.1)
            load_config = self.configuration.load_profile
            asset_parameters = self._asset_parameters(asset)
            cycle_fraction = (
                (operating_load - load_config.base)
                / max(load_config.amplitude, 1e-9)
                * asset_parameters.load_scale
            )
            for measurement_name, signal in asset_profile.signals.items():
                measurement_type = MeasurementType(measurement_name)
                sensor_profile = self.configuration.sensors.get(measurement_name)
                if sensor_profile is None:
                    raise ValueError(f"No sensor profile for measurement: {measurement_name}")
                if self.tick % sensor_profile.sample_every_ticks:
                    continue
                targeted_sensor = measurement_name == (
                    self.scenario_measurements.get(asset.asset_id) or "vibration_rms"
                )
                sensor_fault = scenario_profile.sensor_fault if targeted_sensor else None
                if sensor_fault == "dropout":
                    continue
                seasonality = (
                    math.sin((cycle_tick + asset_index * 3) / 12)
                    * signal.baseline
                    * signal.seasonality_fraction
                )
                noise_scale = sensor_profile.noise_multiplier
                if sensor_fault == "noise_increase":
                    noise_scale *= 8
                noise_sigma = max(signal.baseline * signal.noise_fraction, signal.noise_floor)
                innovation = float(
                    self._rngs[(asset.asset_id, measurement_name, "noise")].normal(
                        0,
                        noise_sigma * self.noise_scale * noise_scale,
                    )
                )
                noise_key = (asset.asset_id, measurement_name)
                ar1 = sensor_profile.noise_ar1
                noise = (
                    ar1 * self._noise_state.get(noise_key, 0.0)
                    + math.sqrt(1 - ar1 * ar1) * innovation
                )
                self._noise_state[noise_key] = noise
                baseline = signal.baseline * asset_parameters.baseline_scale
                if measurement_type is MeasurementType.TEMPERATURE:
                    nominal_load = load_config.base + load_config.amplitude * 0.5
                    value = asset_profile.ambient_temperature_c + (
                        baseline - asset_profile.ambient_temperature_c
                    ) * (operating_load / max(nominal_load, 1e-9))
                    value += seasonality + noise
                else:
                    value = (
                        baseline
                        + baseline * signal.load_fraction * cycle_fraction
                        + seasonality
                        + noise
                    )
                if sensor_fault == "spike" and self.tick == scenario_start:
                    value += max(abs(signal.baseline) * 0.5, 1.0) * severity
                elif sensor_fault == "bias_step" and elapsed >= 1:
                    value += max(abs(signal.baseline) * 0.2, 0.1) * severity
                elif sensor_fault in {"stuck_at", "flat_line"}:
                    value = self._sensor_state.get((asset.asset_id, measurement_name), baseline)

                fault_severity = severity
                if (
                    scenario_profile.intermittent_period_ticks is not None
                    and scenario_profile.intermittent_active_ticks is not None
                    and elapsed % scenario_profile.intermittent_period_ticks
                    >= scenario_profile.intermittent_active_ticks
                ):
                    fault_severity = 0.0
                recovery_after = self.scenario_recovery_ticks.get(asset.asset_id)
                if recovery_after is not None and elapsed >= recovery_after:
                    recovery_length = max(1, (duration or recovery_after + 20) - recovery_after)
                    fault_severity *= max(0.0, 1 - (elapsed - recovery_after) / recovery_length)
                self.health[(asset.asset_id, scenario_profile.health_variable)] = (
                    self._degradation(scenario_profile, elapsed) * fault_severity
                )
                value += self._fault_effect(scenario, measurement_name, elapsed) * fault_severity
                if measurement_type is MeasurementType.TEMPERATURE:
                    thermal_key = (asset.asset_id, measurement_name)
                    prior_temperature = self._thermal_state.get(thermal_key, baseline)
                    thermal_alpha = (
                        1.0
                        if self.tick_seconds <= 0
                        else 1
                        - math.exp(
                            -self.tick_seconds
                            / (
                                asset_profile.thermal_time_constant_seconds
                                * asset_parameters.thermal_time_constant_scale
                            )
                        )
                    )
                    value = prior_temperature + thermal_alpha * (value - prior_temperature)
                    self._thermal_state[thermal_key] = value
                if measurement_type is MeasurementType.CURRENT and process_state == "starting":
                    value *= asset_profile.inrush_multiplier
                elif measurement_type is MeasurementType.CURRENT and process_state in {
                    "stopped",
                    "stopping",
                }:
                    value = 0.0
                sensor_key = (asset.asset_id, measurement_name)
                prior_sensor_value = self._sensor_state.get(sensor_key, value)
                value = prior_sensor_value + sensor_profile.lag_alpha * (value - prior_sensor_value)
                value = (
                    value * sensor_profile.gain
                    + sensor_profile.offset
                    + sensor_profile.drift_per_day * self.tick * self.tick_seconds / 86400
                )
                if sensor_profile.quantization:
                    value = round(value / sensor_profile.quantization) * sensor_profile.quantization
                quality_flag = (
                    QualityFlag.BAD if sensor_fault == "bad_quality" else QualityFlag.GOOD
                )
                if sensor_profile.minimum is not None and value < sensor_profile.minimum:
                    value = sensor_profile.minimum
                    quality_flag = QualityFlag.UNCERTAIN
                if sensor_profile.maximum is not None and value > sensor_profile.maximum:
                    value = sensor_profile.maximum
                    quality_flag = QualityFlag.UNCERTAIN
                self._sensor_state[sensor_key] = value
                jitter = float(
                    self._rngs[(asset.asset_id, measurement_name, "timestamp")].normal(
                        0, sensor_profile.timestamp_jitter_seconds
                    )
                )
                timestamp_utc = now + timedelta(seconds=jitter)
                if sensor_fault == "out_of_order":
                    skew_direction = 1 if self.tick % 2 == 0 else -1
                    timestamp_utc = now + timedelta(seconds=self.tick_seconds * 2 * skew_direction)
                unit = signal.unit
                if sensor_fault == "unit_flip":
                    unit = "unknown"
                    quality_flag = QualityFlag.UNCERTAIN
                elif sensor_fault == "swapped_channels":
                    quality_flag = QualityFlag.UNCERTAIN
                    swapped_name = sensor_profile.swapped_measurement or next(
                        name for name in asset_profile.signals if name != measurement_name
                    )
                    swapped_signal = asset_profile.signals[swapped_name]
                    value = self._sensor_state.get(
                        (asset.asset_id, swapped_name), swapped_signal.baseline
                    )
                    unit = swapped_signal.unit
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
        readings = self._transport(readings)
        self.clock.advance()
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
                await asyncio.sleep(min(self.clock.sleep_seconds, 0.1))
                continue
            yield self.generate_tick()
            await asyncio.sleep(self.clock.sleep_seconds)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def reset(self, *, seed: int | None = None) -> None:
        self.seed = self.seed if seed is None else seed
        self.clock.reset()
        self._rngs = self._spawn_rngs(self.seed)
        self.scenarios = {asset.asset_id: "healthy" for asset in self.assets}
        self.scenario_started_ticks.clear()
        self.scenario_durations.clear()
        self.scenario_severities.clear()
        self.scenario_seeds.clear()
        self.scenario_ids.clear()
        self.scenario_measurements.clear()
        self.scenario_recovery_ticks.clear()
        self.scenario_counter = 0
        self._noise_state.clear()
        self.health.clear()
        self._transport_pending.clear()
        self.transport_dropped = 0
        self.process_states = {asset.asset_id: "running" for asset in self.assets}
        self._process_state_started = {asset.asset_id: 0 for asset in self.assets}
        self._scenario_previous_state.clear()
        self._sensor_state.clear()
        self._thermal_state = {
            (asset.asset_id, MeasurementType.TEMPERATURE.value): self._initial_temperature(asset)
            for asset in self.assets
        }
        self._load_state = {
            asset.asset_id: self.configuration.load_profile.base for asset in self.assets
        }
        self.paused = False
