"""Validated YAML-backed simulator profiles, scenarios, and sensor models."""

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: float
    unit: str = Field(min_length=1)
    load_fraction: float = Field(ge=0)
    noise_fraction: float = Field(ge=0)
    noise_floor: float = Field(ge=0)
    seasonality_fraction: float = Field(default=0.015, ge=0)


class AssetClassProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ambient_temperature_c: float
    thermal_time_constant_seconds: float = Field(gt=0)
    startup_ticks: int = Field(default=3, ge=1)
    inrush_multiplier: float = Field(default=2.0, ge=1)
    signals: dict[str, SignalProfile]


class LoadProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["sine", "schedule", "random_walk", "csv_replay"] = "sine"
    base: float = Field(ge=0, le=1)
    amplitude: float = Field(ge=0, le=1)
    phase_offset_per_asset: float = 0.6
    schedule: list[float] | None = None
    csv_replay_path: str | None = None

    @model_validator(mode="after")
    def validate_source_data(self) -> "LoadProfile":
        if self.source == "schedule" and not self.schedule:
            raise ValueError("schedule load profiles require schedule values")
        if self.source == "csv_replay" and not self.csv_replay_path:
            raise ValueError("csv_replay load profiles require csv_replay_path")
        if self.schedule and any(not 0 <= value <= 1 for value in self.schedule):
            raise ValueError("schedule load values must be between 0 and 1")
        return self


class ScenarioProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effects_per_tick: dict[str, float] = Field(default_factory=dict)
    components: list[str] = Field(default_factory=list)
    health_variable: str = "degradation"
    curve: Literal["linear", "exponential", "stepwise", "sigmoid", "bursty", "weibull"] = "linear"
    curve_rate: float = Field(default=0.01, gt=0)
    curve_shape: float = Field(default=2, gt=0)
    curve_period_ticks: int = Field(default=8, ge=1)
    onset_delay_ticks: int = Field(default=2, ge=0)
    process_state: Literal["stopped", "starting", "running", "idle", "stopping"] | None = None
    sensor_fault: (
        Literal[
            "spike",
            "stuck_at",
            "flat_line",
            "dropout",
            "bias_step",
            "noise_increase",
            "unit_flip",
            "swapped_channels",
            "bad_quality",
            "out_of_order",
        ]
        | None
    ) = None
    intermittent_period_ticks: int | None = Field(default=None, gt=0)
    intermittent_active_ticks: int | None = Field(default=None, ge=0)


class SensorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_every_ticks: int = Field(default=1, ge=1)
    timestamp_jitter_seconds: float = Field(default=0, ge=0)
    gain: float = Field(default=1, gt=0)
    offset: float = 0
    quantization: float = Field(default=0.0001, ge=0)
    lag_alpha: float = Field(default=1, gt=0, le=1)
    noise_multiplier: float = Field(default=1, ge=0)
    noise_ar1: float = Field(default=0, ge=0, lt=1)
    minimum: float | None = None
    maximum: float | None = None
    drift_per_day: float = 0
    swapped_measurement: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "SensorProfile":
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError("sensor minimum must be less than maximum")
        return self


class AssetParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_scale: float = Field(default=1, gt=0)
    load_scale: float = Field(default=1, gt=0)
    thermal_time_constant_scale: float = Field(default=1, gt=0)


class TransportProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latency_ticks: int = Field(default=0, ge=0)
    jitter_ticks: int = Field(default=0, ge=0)
    loss_probability: float = Field(default=0, ge=0, le=1)
    duplicate_probability: float = Field(default=0, ge=0, le=1)
    out_of_order_probability: float = Field(default=0, ge=0, le=1)
    clock_skew_seconds: float = 0
    outage_start_tick: int = Field(default=0, ge=0)
    outage_duration_ticks: int = Field(default=0, ge=0)
    buffer_capacity: int = Field(default=10000, ge=1)


class BearingGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rolling_elements: int = Field(default=8, ge=3)
    ball_diameter_mm: float = Field(default=8, gt=0)
    pitch_diameter_mm: float = Field(default=40, gt=0)
    contact_angle_degrees: float = Field(default=0, ge=0, lt=90)

    @model_validator(mode="after")
    def validate_geometry(self) -> "BearingGeometry":
        if self.ball_diameter_mm >= self.pitch_diameter_mm:
            raise ValueError("ball diameter must be smaller than pitch diameter")
        return self


class VibrationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_rate_hz: int = Field(default=12800, ge=1000, le=51200)
    duration_seconds: float = Field(default=1, gt=0, le=5)
    shaft_frequency_hz: float = Field(default=25, gt=0)
    resonance_hz: float = Field(default=3000, gt=0)
    decay_seconds: float = Field(default=0.003, gt=0)
    harmonic_amplitudes: list[float] = Field(default_factory=lambda: [0.1, 0.04, 0.02])
    broadband_sigma: float = Field(default=0.02, ge=0)
    impulse_amplitude: float = Field(default=3, ge=0)
    modulation_fraction: float = Field(default=0.2, ge=0, le=1)
    defect: Literal["outer", "inner"] = "outer"
    bearing_geometry: BearingGeometry = Field(default_factory=BearingGeometry)

    @model_validator(mode="after")
    def validate_bandwidth(self) -> "VibrationProfile":
        highest_harmonic = self.shaft_frequency_hz * len(self.harmonic_amplitudes)
        if max(self.resonance_hz, highest_harmonic) >= self.sample_rate_hz / 2:
            raise ValueError("raw vibration frequencies must be below Nyquist")
        return self


class SimulatorConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    master_seed: int
    tick_seconds: float = Field(gt=0)
    operating_cycle_ticks: int = Field(ge=1)
    load_profile: LoadProfile
    asset_classes: dict[str, AssetClassProfile]
    asset_parameters: dict[str, AssetParameters] = Field(default_factory=dict)
    scenarios: dict[str, ScenarioProfile]
    sensors: dict[str, SensorProfile]
    transport: TransportProfile = Field(default_factory=TransportProfile)
    vibration: VibrationProfile = Field(default_factory=VibrationProfile)

    @model_validator(mode="after")
    def validate_components(self) -> "SimulatorConfiguration":
        def visit(name: str, ancestors: set[str]) -> None:
            if name not in self.scenarios:
                raise ValueError(f"Unknown scenario component: {name}")
            if name in ancestors:
                raise ValueError(f"Cyclic scenario component: {name}")
            for component in self.scenarios[name].components:
                visit(component, ancestors | {name})

        for name in self.scenarios:
            visit(name, set())
        return self

    @property
    def config_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def load_simulator_configuration(config_dir: Path | None = None) -> SimulatorConfiguration:
    """Load and validate the required profile/scenario/sensor YAML documents."""
    root = config_dir or Path(__file__).resolve().parents[3] / "data" / "simulator"
    profiles = yaml.safe_load((root / "profiles" / "default.yaml").read_text(encoding="utf-8"))
    scenarios = yaml.safe_load((root / "scenarios" / "default.yaml").read_text(encoding="utf-8"))
    sensors = yaml.safe_load((root / "sensors" / "default.yaml").read_text(encoding="utf-8"))
    return SimulatorConfiguration.model_validate(
        {**profiles, "scenarios": scenarios["scenarios"], "sensors": sensors["sensors"]}
    )


def write_simulator_configuration(
    configuration: SimulatorConfiguration,
    config_dir: Path | None = None,
) -> None:
    """Persist a validated config model back into its three YAML source files."""
    root = config_dir or Path(__file__).resolve().parents[3] / "data" / "simulator"
    documents = {
        root / "profiles" / "default.yaml": configuration.model_dump(
            mode="json",
            exclude={"scenarios", "sensors"},
        ),
        root / "scenarios" / "default.yaml": {
            "scenarios": {
                name: profile.model_dump(mode="json")
                for name, profile in configuration.scenarios.items()
            }
        },
        root / "sensors" / "default.yaml": {
            "sensors": {
                name: profile.model_dump(mode="json")
                for name, profile in configuration.sensors.items()
            }
        },
    }
    temporary_paths: list[tuple[Path, Path]] = []
    try:
        for path, document in documents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
            temporary_paths.append((temporary, path))
        for temporary, path in temporary_paths:
            temporary.replace(path)
    finally:
        for temporary, _ in temporary_paths:
            temporary.unlink(missing_ok=True)
