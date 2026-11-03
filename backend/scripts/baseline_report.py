"""Reproduce the current 300-tick detection baseline with a fixed seed."""

import asyncio
import importlib.metadata
import importlib.util
import json
import platform
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import app.datapulse.pipeline as pipeline_module
import app.datapulse.simulator as simulator_module
from app.datapulse.pipeline import PipelineRunner
from app.datapulse.simulator import TelemetrySimulator

SEED = 17
TICKS = 300
TICK_SECONDS = 5.0
WARMUP_TICKS = 10
FAULT_ASSET = "WD-001"


class DeterministicClock:
    """Fixed event clock for deterministic suppression reproduction."""

    current = datetime(2026, 1, 1, tzinfo=UTC)

    @classmethod
    def reset(cls) -> None:
        cls.current = datetime(2026, 1, 1, tzinfo=UTC)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = cls.current
        cls.current += timedelta(seconds=1)
        return value if tz is not None else value.replace(tzinfo=None)


class DeterministicSimulatorClock(DeterministicClock):
    """Advance telemetry time by exactly one configured simulation tick."""

    step_seconds = TICK_SECONDS

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = cls.current
        cls.current += timedelta(seconds=cls.step_seconds)
        return value if tz is not None else value.replace(tzinfo=None)


async def _run_case(
    scenario: str | None,
    *,
    seed: int,
    ticks: int,
    tick_seconds: float,
) -> dict[str, Any]:
    simulator = TelemetrySimulator(seed=seed, tick_seconds=tick_seconds)
    scenario_config = None
    if scenario is not None:
        scenario_config = simulator.inject(
            FAULT_ASSET,
            scenario,
            severity=0.8,
            duration_ticks=ticks,
            seed=seed,
        )
    runner = PipelineRunner(simulator)
    for _ in range(ticks):
        await runner.process_tick()

    by_asset = Counter(anomaly.asset_id for anomaly in runner.anomalies)
    by_type = Counter(anomaly.anomaly_type for anomaly in runner.anomalies)
    by_asset_type = Counter(
        (anomaly.asset_id, anomaly.anomaly_type) for anomaly in runner.anomalies
    )
    startup = [
        anomaly for anomaly in runner.anomalies if (anomaly.detected_at_tick or 0) < WARMUP_TICKS
    ]
    fault_events = [
        anomaly
        for anomaly in runner.anomalies
        if scenario_config is not None
        and anomaly.asset_id == FAULT_ASSET
        and anomaly.scenario_id == scenario_config["scenario_id"]
        and anomaly.detected_at_tick is not None
    ]
    first_fault_tick = min((anomaly.detected_at_tick for anomaly in fault_events), default=None)
    asset_hours = len(simulator.assets) * ticks * tick_seconds / 3600
    return {
        "scenario": scenario or "healthy",
        "seed": seed,
        "ticks": ticks,
        "tick_seconds": tick_seconds,
        "asset_count": len(simulator.assets),
        "detector_available": runner.isolation_forest.available,
        "anomaly_events": len(runner.anomalies),
        "suppressed_alerts": sum(runner.suppressor.counts.values()),
        "suppression_reasons": dict(sorted(runner.suppressor.counts.items())),
        "startup_events_before_tick_10": len(startup),
        "healthy_events_per_asset_hour": round(len(runner.anomalies) / asset_hours, 4)
        if scenario is None
        else None,
        "events_by_asset": dict(sorted(by_asset.items())),
        "events_by_type": dict(sorted(by_type.items())),
        "events_by_asset_and_type": {
            f"{asset_id}/{anomaly_type}": count
            for (asset_id, anomaly_type), count in sorted(by_asset_type.items())
        },
        "target_scenario_id": scenario_config["scenario_id"] if scenario_config else None,
        "target_fault_detected": bool(fault_events),
        "target_fault_detection_latency_ticks": (
            first_fault_tick - scenario_config["start_tick"]
            if first_fault_tick is not None and scenario_config is not None
            else None
        ),
        "cross_asset_events_during_fault": sum(
            anomaly.asset_id != FAULT_ASSET
            for anomaly in runner.anomalies
            if scenario_config is not None
        ),
    }


def run_baseline(
    *,
    seed: int = SEED,
    ticks: int = TICKS,
    tick_seconds: float = TICK_SECONDS,
) -> dict[str, Any]:
    """Run healthy and fault cases with deterministic telemetry and event clocks."""
    original_pipeline_datetime = pipeline_module.datetime
    original_simulator_datetime = simulator_module.datetime
    try:
        pipeline_module.datetime = DeterministicClock
        simulator_module.datetime = DeterministicSimulatorClock
        DeterministicSimulatorClock.step_seconds = tick_seconds
        results = []
        for scenario in (None, "bearing_wear"):
            DeterministicClock.reset()
            DeterministicSimulatorClock.reset()
            results.append(
                asyncio.run(
                    _run_case(
                        scenario,
                        seed=seed,
                        ticks=ticks,
                        tick_seconds=tick_seconds,
                    )
                )
            )
    finally:
        pipeline_module.datetime = original_pipeline_datetime
        simulator_module.datetime = original_simulator_datetime
    try:
        sklearn_version = importlib.metadata.version("scikit-learn")
    except importlib.metadata.PackageNotFoundError:
        sklearn_version = None
    return {
        "status": "measured_on_synthetic_data",
        "environment": {
            "python": platform.python_version(),
            "scikit_learn": sklearn_version,
            "isolation_forest_module_available": importlib.util.find_spec("sklearn") is not None,
        },
        "clock_note": (
            "The baseline harness supplies a deterministic simulation timestamp per tick and "
            "a deterministic event timestamp per detector call. This makes the before-picture "
            "repeatable while preserving the code's known wall-clock suppression behavior."
        ),
        "parameters": {"seed": seed, "ticks": ticks, "tick_seconds": tick_seconds},
        "reported_reference_from_issue": {
            "healthy_300_tick_anomalies": 20,
            "healthy_300_tick_suppressed": 1248,
            "bearing_wear_startup_assets_with_events": 5,
            "bearing_wear_startup_tick": 0,
        },
        "phase0_local_reference": {
            "healthy_300_tick_anomalies": 16,
            "healthy_300_tick_suppressed": 1006,
            "bearing_wear_total_anomalies": 14,
            "bearing_wear_suppressed": 1237,
            "bearing_wear_target_latency_ticks": 0,
            "bearing_wear_cross_asset_events": 12,
        },
        "runs": results,
    }


def render_report(result: dict[str, Any]) -> str:
    healthy, fault = result["runs"]
    parameters = result["parameters"]
    phase0 = result["phase0_local_reference"]
    healthy_summary = (
        f"| Healthy, {parameters['ticks']} ticks | 20 anomalies, 1,248 suppressed | "
        f"{phase0['healthy_300_tick_anomalies']} anomalies, "
        f"{phase0['healthy_300_tick_suppressed']} suppressed | "
        f"{healthy['anomaly_events']} anomalies, {healthy['suppressed_alerts']} suppressed |"
    )
    fault_summary = (
        f"| WD-001 bearing wear, {parameters['ticks']} ticks | "
        "Events on all five assets at tick 0 | "
        f"{phase0['bearing_wear_total_anomalies']} total anomalies; target latency: "
        f"{phase0['bearing_wear_target_latency_ticks']} ticks; cross-asset events: "
        f"{phase0['bearing_wear_cross_asset_events']} | "
        f"{fault['anomaly_events']} total anomalies; target detected: "
        f"{fault['target_fault_detected']}; target latency: "
        f"{fault['target_fault_detection_latency_ticks']} ticks; cross-asset events: "
        f"{fault['cross_asset_events_during_fault']} |"
    )
    output = [
        "# Detection Baseline and Phase 1 Results",
        "",
        (
            "This report preserves the Phase 0 before-picture and compares it with the "
            "Phase 1 detector changes. All runs use synthetic simulator data; these figures "
            "are not real-plant performance claims."
        ),
        "",
        "## Reproduction",
        "",
        "```powershell",
        "Push-Location backend",
        "python -m scripts.baseline_report",
        "Pop-Location",
        "```",
        "",
        (
            f"Seed `{parameters['seed']}`, `{parameters['ticks']}` ticks, "
            f"`{parameters['tick_seconds']}` simulated seconds per tick, five seeded assets."
        ),
        (
            f"Python `{result['environment']['python']}`; scikit-learn "
            f"`{result['environment']['scikit_learn'] or 'not installed'}`."
        ),
        "",
        "## Reference and Reproduction",
        "",
        "| Run | Prompt-reported | Phase 0 local | Phase 1 local |",
        "| --- | --- | --- | --- |",
        healthy_summary,
        fault_summary,
        "",
        (
            "The prompt-reported figures are preserved as operator-provided reference values; "
            "the local reproduction is not forced to match them. Differences must be explained "
            "by seed, dependency availability, and simulator/runtime changes before treating "
            "them as comparable."
        ),
        "",
        "## Phase 1 Changes",
        "",
        (
            "- Simulator noise uses independent per-asset random streams; scenario reseeding "
            "no longer perturbs other assets."
        ),
        (
            "- SPC histories and CUSUM state are keyed per asset and measurement, with "
            "phase-conditioned residuals trained from eight healthy operating cycles."
        ),
        (
            "- SPC uses a five-sigma point limit and a 30-unit CUSUM limit, calibrated against "
            "the fixed-seed synthetic benchmark."
        ),
        (
            "- Optional Isolation Forest scores are calibrated against the training-score tail "
            "and healthy input range rather than mapping the training minimum to maximum risk."
        ),
        "",
        "## Reproduced Metrics",
        "",
        "| Metric | Healthy | WD-001 bearing wear |",
        "| --- | ---: | ---: |",
        f"| Detector events | {healthy['anomaly_events']} | {fault['anomaly_events']} |",
        f"| Suppressed alerts | {healthy['suppressed_alerts']} | {fault['suppressed_alerts']} |",
        (
            f"| Startup events before tick 10 | {healthy['startup_events_before_tick_10']} | "
            f"{fault['startup_events_before_tick_10']} |"
        ),
        f"| Events per asset-hour | {healthy['healthy_events_per_asset_hour']} | N/A |",
        f"| Target fault detected | N/A | {fault['target_fault_detected']} |",
        (
            f"| Target detection latency (ticks) | N/A | "
            f"{fault['target_fault_detection_latency_ticks']} |"
        ),
        f"| Cross-asset events during fault | N/A | {fault['cross_asset_events_during_fault']} |",
        "",
        "### Events by Asset/Type",
        "",
        "Healthy:",
        "```json",
        json.dumps(healthy["events_by_asset_and_type"], indent=2, sort_keys=True),
        "```",
        "Fault injection:",
        "```json",
        json.dumps(fault["events_by_asset_and_type"], indent=2, sort_keys=True),
        "```",
        "",
        "## Limitations Observed",
        "",
        result["clock_note"],
        (
            "The isolation-forest detector is marked available only when scikit-learn is "
            "installed; a report with it unavailable does not represent the full declared "
            "runtime dependency set."
        ),
        (
            "Healthy detector events are false-alert candidates. Cross-asset events during a "
            "single-asset fault are not attributed to the injected fault. Phase 1 threshold "
            "calibration is synthetic and fixed-seed; independent seeds and real operating "
            "data are needed to assess generalization."
        ),
        "",
        "## Phase 1 Regression Coverage",
        "",
        "The former strict expected-failure checks are now active passing regressions:",
        "",
        "- `test_healthy_300_ticks_have_no_post_warmup_anomalies`",
        "- `test_spc_baseline_isolated_between_assets_of_same_class`",
        "- `test_reseeding_one_asset_does_not_change_other_asset_readings`",
        "",
    ]
    return "\n".join(output)


def main() -> None:
    result = run_baseline()
    report = render_report(result)
    output = Path(__file__).resolve().parents[2] / "docs" / "BASELINE.md"
    output.write_text(report, encoding="utf-8", newline="\n")
    print(report)


if __name__ == "__main__":
    main()
