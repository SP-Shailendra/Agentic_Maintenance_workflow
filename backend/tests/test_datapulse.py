import asyncio
from datetime import UTC, datetime, timedelta

from app.datapulse.normalizer import TelemetryNormalizer
from app.datapulse.pipeline import PipelineRunner
from app.datapulse.simulator import TelemetrySimulator
from app.datapulse_ai.detection.ensemble import EnsembleDetector
from app.datapulse_ai.detection.isolation_forest import IsolationForestDetector
from app.datapulse_ai.detection.spc import SPCDetector
from app.datapulse_ai.detection.suppression import AlertSuppressor
from app.schemas.domain import MeasurementType, TelemetryReading


def test_seeded_simulator_repeats_identically_and_emits_all_assets() -> None:
    first = TelemetrySimulator(seed=4, tick_seconds=0)
    second = TelemetrySimulator(seed=4, tick_seconds=0)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    assert [item.model_dump() for item in first.generate_tick(timestamp)] == [
        item.model_dump() for item in second.generate_tick(timestamp)
    ]
    assert len(first.generate_tick(timestamp)) == 20


def test_normalizer_converts_units_deduplicates_and_drops_old_data() -> None:
    normalizer = TelemetryNormalizer()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    reading = TelemetryReading(
        asset_id="IC-001", sensor_id="temp", timestamp_utc=timestamp,
        measurement_type=MeasurementType.TEMPERATURE, value=68, unit="degF",
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
        True, "duplicate_window"
    )
    assert suppressor.counts["duplicate_window"] == 1


def test_pipeline_processes_simulated_readings() -> None:
    async def run() -> None:
        simulator = TelemetrySimulator(seed=3, tick_seconds=0)
        runner = PipelineRunner(simulator)
        await runner.process_tick()
        assert len(runner.readings) == 20
        assert runner.bus.published == 20

    asyncio.run(run())


def test_isolation_forest_is_optional_without_declared_ml_extras() -> None:
    detector = IsolationForestDetector()
    result = detector.train({("test", "temperature"): [float(value) for value in range(20)]})
    if not result:
        assert detector.score("test", "temperature", 100.0) == 0.0
    else:
        assert 0.0 <= detector.score("test", "temperature", 100.0) <= 1.0