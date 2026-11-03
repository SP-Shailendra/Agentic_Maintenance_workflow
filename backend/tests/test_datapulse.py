import asyncio
import hashlib
import importlib.util
import json
import os
from datetime import UTC, datetime, timedelta
from statistics import correlation

import pytest

from app.datapulse.configuration import (
    SimulatorConfiguration,
    load_simulator_configuration,
    write_simulator_configuration,
)
from app.datapulse.normalizer import TelemetryNormalizer
from app.datapulse.pipeline import PipelineRunner
from app.datapulse.simulator import SimClock, TelemetrySimulator
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


def test_simulator_yaml_configuration_is_valid_and_hash_stable() -> None:
    configuration = load_simulator_configuration()
    replay = load_simulator_configuration()

    assert configuration.config_hash == replay.config_hash
    assert configuration.asset_parameters["WD-001"].baseline_scale != (
        configuration.asset_parameters["WD-002"].baseline_scale
    )
    invalid = configuration.model_dump()
    invalid["tick_seconds"] = 0
    with pytest.raises(ValueError):
        SimulatorConfiguration.model_validate(invalid)


def test_simulator_configuration_yaml_round_trip(tmp_path) -> None:
    original = load_simulator_configuration()
    write_simulator_configuration(original, tmp_path)

    reloaded = load_simulator_configuration(tmp_path)

    assert reloaded.config_hash == original.config_hash


def test_sim_clock_speeds_are_deterministic_and_validated() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = SimClock(10, t0=start)
    assert clock.now == start
    assert clock.advance() == start
    assert clock.now == start + timedelta(seconds=10)
    clock.set_speed(10)
    assert clock.sleep_seconds == 1
    clock.set_speed(100)
    assert clock.sleep_seconds == 0.1
    clock.set_speed("max")
    assert clock.sleep_seconds == 0
    with pytest.raises(ValueError):
        clock.set_speed(5)


def test_sensor_noise_autocorrelation_matches_yaml_profile() -> None:
    config_data = load_simulator_configuration().model_dump()
    config_data["load_profile"]["amplitude"] = 0
    for profile in config_data["asset_classes"].values():
        current = profile["signals"]["current"]
        current["load_fraction"] = 0
        current["seasonality_fraction"] = 0
    current_sensor = config_data["sensors"]["current"]
    current_sensor.update(
        {
            "timestamp_jitter_seconds": 0,
            "lag_alpha": 1,
            "noise_ar1": 0.75,
            "quantization": 0,
        }
    )
    config = SimulatorConfiguration.model_validate(config_data)
    simulator = TelemetrySimulator(seed=74, tick_seconds=1, configuration=config)
    values = []
    for _ in range(600):
        readings = simulator.generate_tick()
        values.append(
            next(
                reading.value
                for reading in readings
                if reading.asset_id == "WD-001"
                and reading.measurement_type is MeasurementType.CURRENT
            )
        )

    assert abs(correlation(values[:-1], values[1:]) - 0.75) < 0.1


def test_process_state_stops_current_and_applies_startup_inrush() -> None:
    simulator = TelemetrySimulator(seed=42, tick_seconds=0, noise_scale=0)
    assert simulator.set_operating_state("TG-001", "stopped") == "stopped"
    stopped = simulator.generate_tick()
    stopped_current = next(
        reading.value
        for reading in stopped
        if reading.asset_id == "TG-001" and reading.measurement_type is MeasurementType.CURRENT
    )
    assert stopped_current == 0

    assert simulator.set_operating_state("TG-001", "running") == "starting"
    starting = simulator.generate_tick()
    startup_current = next(
        reading.value
        for reading in starting
        if reading.asset_id == "TG-001" and reading.measurement_type is MeasurementType.CURRENT
    )
    assert startup_current > stopped_current
    for _ in range(simulator._asset_profile(simulator.assets[2]).startup_ticks):
        simulator.generate_tick()
    assert simulator.process_states["TG-001"] == "running"


def test_healthy_means_are_stable_across_thirty_seeds() -> None:
    per_seed_means = []
    for seed in range(30):
        simulator = TelemetrySimulator(seed=seed, tick_seconds=0, operating_cycle_ticks=30)
        readings = [
            reading.value
            for _ in range(30)
            for reading in simulator.generate_tick()
            if reading.asset_id == "WD-001"
            and reading.measurement_type is MeasurementType.VIBRATION_RMS
        ]
        per_seed_means.append(sum(readings) / len(readings))

    center = sum(per_seed_means) / len(per_seed_means)
    assert max(per_seed_means) - min(per_seed_means) < center * 0.08


def test_safety_scenarios_are_not_restricted_to_specific_asset_ids() -> None:
    cases = (
        ("WD-001", "safety_critical_case"),
        ("TG-001", "unclassified_case"),
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for asset_id, scenario in cases:
        healthy = TelemetrySimulator(seed=18, tick_seconds=0, noise_scale=0)
        faulted = TelemetrySimulator(seed=18, tick_seconds=0, noise_scale=0)
        faulted.inject(asset_id, scenario, duration_ticks=10)
        healthy_readings = []
        faulted_readings = []
        for tick in range(6):
            timestamp = start + timedelta(seconds=tick)
            healthy_readings = healthy.generate_tick(timestamp)
            faulted_readings = faulted.generate_tick(timestamp)
        measurement = next(
            reading.measurement_type
            for reading in faulted_readings
            if reading.asset_id == asset_id
            and reading.measurement_type == MeasurementType.VIBRATION_RMS
        )
        healthy_value = next(
            reading.value
            for reading in healthy_readings
            if reading.asset_id == asset_id and reading.measurement_type == measurement
        )
        faulted_value = next(
            reading.value
            for reading in faulted_readings
            if reading.asset_id == asset_id and reading.measurement_type == measurement
        )
        assert faulted_value > healthy_value


def test_bearing_wear_vibration_signature_precedes_temperature() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    healthy = TelemetrySimulator(seed=18, tick_seconds=5, noise_scale=0)
    faulted = TelemetrySimulator(seed=18, tick_seconds=5, noise_scale=0)
    faulted.inject("WD-001", "bearing_wear", severity=1, duration_ticks=100)
    first_vibration_tick = None
    first_temperature_tick = None

    for tick in range(100):
        time = timestamp + timedelta(seconds=tick * 5)
        healthy_readings = healthy.generate_tick(time)
        faulted_readings = faulted.generate_tick(time)
        for measurement_type, threshold in (
            (MeasurementType.VIBRATION_RMS, 0.1),
            (MeasurementType.TEMPERATURE, 0.05),
        ):
            healthy_value = next(
                reading.value
                for reading in healthy_readings
                if reading.asset_id == "WD-001" and reading.measurement_type is measurement_type
            )
            faulted_value = next(
                reading.value
                for reading in faulted_readings
                if reading.asset_id == "WD-001" and reading.measurement_type is measurement_type
            )
            if faulted_value - healthy_value >= threshold:
                if measurement_type is MeasurementType.VIBRATION_RMS:
                    first_vibration_tick = first_vibration_tick or tick
                else:
                    first_temperature_tick = first_temperature_tick or tick

    assert first_vibration_tick is not None
    assert first_temperature_tick is not None
    assert first_vibration_tick < first_temperature_tick


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


def test_composable_degradation_curves_and_cycle_rejection() -> None:
    from app.datapulse.configuration import ScenarioProfile

    for curve in ("linear", "exponential", "stepwise", "sigmoid", "bursty", "weibull"):
        profile = ScenarioProfile(curve=curve, onset_delay_ticks=0)
        assert TelemetrySimulator._degradation(profile, 0) == 0
        assert TelemetrySimulator._degradation(profile, 16) > 0
    configuration = load_simulator_configuration()
    simulator = TelemetrySimulator(configuration=configuration)
    expected = sum(
        simulator._fault_effect(component, "temperature", 16)
        for component in ("bearing_wear", "fouling")
    )
    assert simulator._fault_effect("compound_fault", "temperature", 16) == expected
    payload = configuration.model_dump()
    payload["scenarios"]["bearing_wear"]["components"] = ["compound_fault"]
    with pytest.raises(ValueError, match="Cyclic"):
        SimulatorConfiguration.model_validate(payload)


def test_transport_outage_store_forward_duplicates_loss_and_reset() -> None:
    configuration = load_simulator_configuration()
    configuration.transport.outage_duration_ticks = 2
    configuration.transport.duplicate_probability = 1
    simulator = TelemetrySimulator(configuration=configuration)
    assert simulator.generate_tick() == []
    assert simulator.generate_tick() == []
    burst = simulator.generate_tick()
    assert len(burst) == 120
    normalizer = TelemetryNormalizer()
    for reading in burst:
        normalizer.normalize(reading)
    assert normalizer.dropped_duplicate == 60
    simulator.reset()
    assert len(simulator._transport_pending) == 0
    configuration.transport.loss_probability = 1
    assert simulator.generate_tick() == []
    assert simulator.transport_dropped == 20


def test_transport_latency_and_clock_skew_preserve_measurement_time() -> None:
    configuration = load_simulator_configuration()
    configuration.transport.latency_ticks = 1
    configuration.transport.clock_skew_seconds = 30
    for sensor in configuration.sensors.values():
        sensor.timestamp_jitter_seconds = 0
    simulator = TelemetrySimulator(configuration=configuration)
    epoch = simulator.clock.now
    assert simulator.generate_tick() == []
    delivered = simulator.generate_tick()
    assert len(delivered) == 20
    assert delivered[0].timestamp_utc == epoch + timedelta(seconds=30)


def test_raw_vibration_determinism_and_bearing_envelope_peak() -> None:
    simulator = TelemetrySimulator(seed=17)
    control = TelemetrySimulator(seed=17)
    healthy = simulator.vibration_window("WD-001")
    assert healthy == control.vibration_window("WD-001")
    fault = simulator.vibration_window("WD-001", severity=0.8)
    assert len(fault["samples"]) == 12800
    assert fault["rms"] > healthy["rms"]
    assert fault["crest_factor"] > healthy["crest_factor"]
    spectrum = fault["envelope_amplitudes"]
    peak = max(range(1, len(spectrum)), key=spectrum.__getitem__)
    assert abs(fault["envelope_frequencies_hz"][peak] - fault["bpfo_hz"]) <= 1
    with pytest.raises(KeyError):
        simulator.vibration_window("missing")
    payload = simulator.configuration.model_dump()
    payload["vibration"]["resonance_hz"] = 10000
    with pytest.raises(ValueError, match="Nyquist"):
        SimulatorConfiguration.model_validate(payload)


def test_default_telemetry_golden_digest() -> None:
    simulator = TelemetrySimulator(seed=17)
    rows = [
        reading.model_dump(mode="json")
        for _tick in range(3)
        for reading in simulator.generate_tick()
    ]
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == "be2101e1eb368f41254aded05f3bdd186b3f293c8c70d958a46a82b81dc9a1b4"


def test_healthy_300_ticks_have_no_post_warmup_anomalies() -> None:
    healthy = run_baseline(ticks=300)["runs"][0]
    assert healthy["anomaly_events"] == healthy["startup_events_before_tick_10"]


def test_spc_baseline_isolated_between_assets_of_same_class() -> None:
    detector = SPCDetector(baseline_size=30)
    for _ in range(30):
        detector.score("wire_draw_motor", "current", "WD-001", 10.0)
    wd002_scores = [detector.score("wire_draw_motor", "current", "WD-002", 20.0) for _ in range(30)]
    assert max(wd002_scores) < 0.1


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


def test_isolation_forest_scores_outliers_but_not_healthy_training_values() -> None:
    pytest.importorskip("sklearn")
    detector = IsolationForestDetector(seed=17)
    training = [1.0 + index / 10_000 for index in range(1_000)]

    assert detector.train({("wire_draw_motor", "vibration_rms"): training})
    assert detector.score("wire_draw_motor", "vibration_rms", 1.05) == 0.0
    assert detector.score("wire_draw_motor", "vibration_rms", 100.0) > 0.9


def test_pipeline_preloads_spc_healthy_baselines_before_fault_ticks() -> None:
    runner = PipelineRunner(TelemetrySimulator(seed=12, tick_seconds=0))
    baseline = runner.spc._history[("WD-001", "vibration_rms")]
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
    assert correlation(currents, temperatures) > 0.6
    assert correlation(currents, vibration) > 0.95


def test_temperature_responds_to_overheat_with_configured_lag() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    healthy = TelemetrySimulator(seed=29, tick_seconds=300, noise_scale=0)
    faulted = TelemetrySimulator(seed=29, tick_seconds=300, noise_scale=0)
    faulted.inject("TG-001", "overheat", severity=1, duration_ticks=None)
    differences: list[float] = []

    for tick in range(12):
        healthy_readings = healthy.generate_tick(timestamp + timedelta(seconds=tick * 300))
        faulted_readings = faulted.generate_tick(timestamp + timedelta(seconds=tick * 300))
        healthy_temperature = next(
            reading.value
            for reading in healthy_readings
            if reading.asset_id == "TG-001"
            and reading.measurement_type is MeasurementType.TEMPERATURE
        )
        faulted_temperature = next(
            reading.value
            for reading in faulted_readings
            if reading.asset_id == "TG-001"
            and reading.measurement_type is MeasurementType.TEMPERATURE
        )
        differences.append(faulted_temperature - healthy_temperature)

    assert differences[2] == 0
    assert differences[3] < differences[6] < differences[-1]


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


@pytest.mark.skipif(
    os.getenv("CI", "").lower() != "true",
    reason="The optional-dependency availability gate runs in CI.",
)
def test_isolation_forest_is_installed_and_trainable_in_ci() -> None:
    assert importlib.util.find_spec("sklearn") is not None
    detector = IsolationForestDetector()
    training = {("wire_draw_motor", "vibration_rms"): [1.0 + index / 100 for index in range(20)]}
    assert detector.train(training)
    assert detector.available
