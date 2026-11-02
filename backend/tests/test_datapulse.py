import asyncio
from datetime import UTC, datetime, timedelta
from statistics import correlation

import pytest

from app.datapulse.normalizer import TelemetryNormalizer
from app.datapulse.pipeline import PipelineRunner
from app.datapulse.simulator import TelemetrySimulator
from app.datapulse_ai.detection.ensemble import EnsembleDetector
from app.datapulse_ai.detection.isolation_forest import IsolationForestDetector
from app.datapulse_ai.detection.spc import SPCDetector
from app.datapulse_ai.detection.suppression import AlertSuppressor
from app.schemas.domain import MeasurementType, QualityFlag, TelemetryReading
from scripts.baseline_report import run_baseline


def test_seeded_simulator_repeats_identically_and_emits_all_assets() -> None:
    first = TelemetrySimulator(seed=4, tick_seconds=0)
    second = TelemetrySimulator(seed=4, tick_seconds=0)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    assert [item.model_dump() for item in first.generate_tick(timestamp)] == [
        item.model_dump() for item in second.generate_tick(timestamp)
    ]
    assert len(first.generate_tick(timestamp)) == 20


def test_seeded_fault_replay_is_identical_across_multiple_ticks() -> None:
    first = TelemetrySimulator(seed=4, tick_seconds=5)
    second = TelemetrySimulator(seed=4, tick_seconds=5)
    first_config = first.inject("WD-001", "intermittent_bearing", seed=31)
    second_config = second.inject("WD-001", "intermittent_bearing", seed=31)
    assert first_config["scenario_id"] == second_config["scenario_id"]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first_replay = [
        [
            reading.model_dump()
            for reading in first.generate_tick(start + timedelta(seconds=tick * 5))
        ]
        for tick in range(16)
    ]
    second_replay = [
        [
            reading.model_dump()
            for reading in second.generate_tick(start + timedelta(seconds=tick * 5))
        ]
        for tick in range(16)
    ]
    assert first_replay == second_replay


def test_baseline_report_is_reproducible_for_fixed_seed() -> None:
    assert run_baseline(ticks=12) == run_baseline(ticks=12)


@pytest.mark.xfail(
    strict=True,
    reason="Known bug: healthy cyclic signals still trigger detector events",
)
def test_healthy_300_ticks_have_no_post_warmup_anomalies() -> None:
    async def run() -> list[object]:
        runner = PipelineRunner(TelemetrySimulator(seed=17, tick_seconds=5))
        for _ in range(300):
            await runner.process_tick()
        return [
            anomaly
            for anomaly in runner.anomalies
            if anomaly.detected_at_tick is not None and anomaly.detected_at_tick >= 10
        ]

    assert asyncio.run(run()) == []


@pytest.mark.xfail(strict=True, reason="Known bug: SPC baseline is shared by asset class")
def test_spc_baseline_isolated_between_assets_of_same_class() -> None:
    detector = SPCDetector(baseline_size=30)
    for _ in range(30):
        detector.score("wire_draw_motor", "current", "WD-001", 10.0)
    wd002_scores = [detector.score("wire_draw_motor", "current", "WD-002", 20.0) for _ in range(30)]
    assert max(wd002_scores) < 0.1


@pytest.mark.xfail(strict=True, reason="Known bug: scenario seed resets the shared fleet RNG")
def test_reseeding_one_asset_does_not_change_other_asset_readings() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    injected = TelemetrySimulator(seed=17, tick_seconds=0)
    control = TelemetrySimulator(seed=17, tick_seconds=0)
    injected.inject("WD-001", "bearing_wear", seed=31)
    injected_readings = injected.generate_tick(timestamp)
    control_readings = control.generate_tick(timestamp)
    injected_other_assets = [
        item.model_dump() for item in injected_readings if item.asset_id != "WD-001"
    ]
    control_other_assets = [
        item.model_dump() for item in control_readings if item.asset_id != "WD-001"
    ]
    assert injected_other_assets == control_other_assets


def test_pipeline_preloads_spc_healthy_baselines_before_fault_ticks() -> None:
    runner = PipelineRunner(TelemetrySimulator(seed=12, tick_seconds=0))
    baseline = runner.spc._history[("wire_draw_motor", "vibration_rms")]
    assert len(baseline) == runner.spc.baseline_size
    score = runner.spc.score("wire_draw_motor", "vibration_rms", "WD-001", 20.0)
    assert score > 0.9


def test_scenario_has_severity_duration_seed_and_clear_controls() -> None:
    simulator = TelemetrySimulator(seed=9, tick_seconds=0)
    config = simulator.inject(
        "WD-001",
        "bearing_wear",
        severity=0.4,
        duration_ticks=2,
        seed=31,
    )
    assert config["severity"] == 0.4
    assert config["duration_ticks"] == 2
    assert simulator.active_scenarios()[0]["remaining_ticks"] == 2
    simulator.generate_tick(datetime(2026, 1, 1, tzinfo=UTC))
    assert simulator.active_scenarios()[0]["remaining_ticks"] == 1
    simulator.generate_tick(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=5))
    assert simulator.active_scenarios() == []

    simulator.inject("WD-001", "overheat", duration_ticks=None)
    assert simulator.clear("WD-001") is True
    assert simulator.active_scenarios() == []


def test_fault_ramp_starts_at_injection_not_simulator_uptime() -> None:
    simulator = TelemetrySimulator(seed=4, tick_seconds=0)
    for _ in range(20):
        simulator.generate_tick(datetime(2026, 1, 1, tzinfo=UTC))
    simulator.inject("WD-001", "bearing_wear", severity=0.8, duration_ticks=20)

    first_tick = simulator.generate_tick(datetime(2026, 1, 1, tzinfo=UTC))
    vibration = next(
        reading.value
        for reading in first_tick
        if reading.asset_id == "WD-001"
        and reading.measurement_type == MeasurementType.VIBRATION_RMS
    )
    assert vibration < 2.5


def test_safety_fault_scenario_does_not_change_other_asset_signals() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    healthy = TelemetrySimulator(seed=18, tick_seconds=0)
    injected = TelemetrySimulator(seed=18, tick_seconds=0)
    injected.inject("IC-001", "safety_critical_case", seed=18)
    healthy_readings = healthy.generate_tick(timestamp)
    injected_readings = injected.generate_tick(timestamp)
    healthy_controls = [reading for reading in healthy_readings if reading.asset_id != "IC-001"]
    injected_controls = [reading for reading in injected_readings if reading.asset_id != "IC-001"]
    assert [reading.model_dump() for reading in injected_controls] == [
        reading.model_dump() for reading in healthy_controls
    ]


def test_operating_cycle_correlates_load_temperature_and_vibration() -> None:
    simulator = TelemetrySimulator(
        seed=3,
        tick_seconds=0,
        operating_cycle_ticks=20,
        noise_scale=0,
    )
    currents: list[float] = []
    temperatures: list[float] = []
    vibration: list[float] = []
    for _ in range(20):
        readings = simulator.generate_tick(datetime(2026, 1, 1, tzinfo=UTC))
        asset_readings = [reading for reading in readings if reading.asset_id == "TG-001"]
        values = {reading.measurement_type: reading.value for reading in asset_readings}
        currents.append(values[MeasurementType.CURRENT])
        temperatures.append(values[MeasurementType.TEMPERATURE])
        vibration.append(values[MeasurementType.VIBRATION_RMS])
    assert correlation(currents, temperatures) > 0.95
    assert correlation(currents, vibration) > 0.95


def test_intermittent_and_recovering_fault_profiles_change_over_time() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    intermittent = TelemetrySimulator(seed=5, tick_seconds=0, noise_scale=0)
    intermittent.inject(
        "WD-001",
        "intermittent_bearing",
        severity=1,
        duration_ticks=24,
        seed=5,
    )
    intermittent_values = []
    for _ in range(16):
        tick = intermittent.generate_tick(timestamp)
        intermittent_values.append(
            next(
                reading.value
                for reading in tick
                if reading.asset_id == "WD-001"
                and reading.measurement_type == MeasurementType.VIBRATION_RMS
            )
        )
    assert intermittent_values[9] > intermittent_values[12]

    recovering = TelemetrySimulator(seed=5, tick_seconds=0, noise_scale=0)
    recovering.inject(
        "WD-001",
        "recovering_bearing_wear",
        severity=1,
        duration_ticks=20,
        recovery_after_ticks=8,
    )
    recovering_values = []
    for _ in range(20):
        tick = recovering.generate_tick(timestamp)
        recovering_values.append(
            next(
                reading.value
                for reading in tick
                if reading.asset_id == "WD-001"
                and reading.measurement_type == MeasurementType.VIBRATION_RMS
            )
        )
    assert recovering_values[7] > recovering_values[-1]


def test_sensor_fault_scenarios_emit_dropout_bad_quality_and_time_skew() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    simulator = TelemetrySimulator(seed=6, tick_seconds=5, noise_scale=0)
    simulator.inject("WD-001", "sensor_dropout", measurement_type="temperature", duration_ticks=3)
    dropout = simulator.generate_tick(timestamp)
    assert not any(
        reading.asset_id == "WD-001" and reading.measurement_type == MeasurementType.TEMPERATURE
        for reading in dropout
    )

    simulator.clear("WD-001")
    simulator.inject("WD-001", "bad_quality", measurement_type="current", duration_ticks=3)
    bad_quality = simulator.generate_tick(timestamp + timedelta(seconds=5))
    current_reading = next(
        reading
        for reading in bad_quality
        if reading.asset_id == "WD-001" and reading.measurement_type == MeasurementType.CURRENT
    )
    assert current_reading.quality_flag == QualityFlag.BAD

    simulator.clear("WD-001")
    simulator.inject("WD-001", "out_of_order", measurement_type="pressure", duration_ticks=3)
    first_skewed = simulator.generate_tick(timestamp + timedelta(seconds=10))
    second_skewed = simulator.generate_tick(timestamp + timedelta(seconds=15))
    first_timestamp = next(
        reading.timestamp_utc
        for reading in first_skewed
        if reading.asset_id == "WD-001" and reading.measurement_type == MeasurementType.PRESSURE
    )
    second_timestamp = next(
        reading.timestamp_utc
        for reading in second_skewed
        if reading.asset_id == "WD-001" and reading.measurement_type == MeasurementType.PRESSURE
    )
    assert second_timestamp < first_timestamp


def test_normalizer_converts_units_deduplicates_and_drops_old_data() -> None:
    normalizer = TelemetryNormalizer()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    reading = TelemetryReading(
        asset_id="IC-001",
        sensor_id="temp",
        timestamp_utc=timestamp,
        measurement_type=MeasurementType.TEMPERATURE,
        value=68,
        unit="degF",
    )
    normalized = normalizer.normalize(reading)
    assert normalized is not None and normalized.unit == "degC" and normalized.value == 20
    assert normalizer.normalize(reading) is None
    old = reading.model_copy(update={"timestamp_utc": timestamp - timedelta(seconds=1)})
    assert normalizer.normalize(old) is None
    assert normalizer.dropped_duplicate == normalizer.dropped_out_of_order == 1


def test_spc_detects_sustained_drift_and_ensemble_applies_weights() -> None:
    detector = SPCDetector(baseline_size=30)
    for _ in range(30):
        detector.score("motor", "vibration_rms", "WD-001", 2.0)
    assert detector.score("motor", "vibration_rms", "WD-001", 4.0) == 1.0
    ensemble = EnsembleDetector(weights={"spc": 0.8, "isolation_forest": 0.2})
    result = ensemble.combine({"vibration_rms": {"spc": 0.8, "isolation_forest": 0.2}})
    assert result.score == 0.68
    assert result.triggered is True


def test_alert_suppression_counts_duplicate_and_quiet_period() -> None:
    suppressor = AlertSuppressor(quiet_minutes=5, dedup_minutes=15)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert suppressor.should_suppress("WD-001", "bearing_wear", now) == (False, None)
    assert suppressor.should_suppress("WD-001", "bearing_wear", now + timedelta(minutes=1)) == (
        True,
        "duplicate_window",
    )
    assert suppressor.counts["duplicate_window"] == 1


def test_pipeline_processes_simulated_readings() -> None:
    async def run() -> None:
        simulator = TelemetrySimulator(seed=3, tick_seconds=0)
        runner = PipelineRunner(simulator)
        await runner.process_tick()
        assert len(runner.readings) == 20
        assert runner.bus.published == 20
        assert runner.bus.consumed == 20
        assert all(
            "scenario_id" not in reading["context"]
            for anomaly in runner.anomalies
            for reading in [anomaly.evidence["features"]]
        )

    asyncio.run(run())


def test_pipeline_pause_stops_background_ticks() -> None:
    async def run() -> None:
        runner = PipelineRunner(TelemetrySimulator(seed=2, tick_seconds=0))
        runner.pause()
        runner.start()
        await asyncio.sleep(0.02)
        await runner.stop()
        assert runner.readings == []

    asyncio.run(run())


def test_isolation_forest_is_optional_without_declared_ml_extras() -> None:
    detector = IsolationForestDetector()
    result = detector.train({("test", "temperature"): [float(value) for value in range(20)]})
    if not result:
        assert detector.score("test", "temperature", 100.0) == 0.0
    else:
        assert 0.0 <= detector.score("test", "temperature", 100.0) <= 1.0
