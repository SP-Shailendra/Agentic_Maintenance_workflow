"""Evaluate anomaly detection against deterministic synthetic scenario labels."""

import json
from pathlib import Path

from app.datapulse.simulator import BASELINES
from app.datapulse_ai.detection.isolation_forest import IsolationForestDetector


def run_evaluation() -> dict[str, float | int | str]:
    training: dict[tuple[str, str], list[float]] = {}
    cases: list[tuple[str, str, float, bool]] = []
    fault_steps = {
        "bearing_wear": {"vibration_rms": 1.8, "temperature": 1.1},
        "overheat": {"temperature": 5.0, "current": 1.4},
        "pressure_drop": {"pressure": -1.5},
        "capacitor_degradation": {"current": 2.5},
    }
    for asset_class, measurements in BASELINES.items():
        for measurement_type, (baseline, _) in measurements.items():
            spread = max(abs(baseline) * 0.015, 0.02)
            samples = [baseline + ((index % 11) - 5) * spread / 5 for index in range(100)]
            key = (asset_class, measurement_type.value)
            training[key] = samples
            for value in samples[:30]:
                cases.append((asset_class, measurement_type.value, value, False))
            for fault in fault_steps.values():
                shift = fault.get(measurement_type.value)
                if shift is not None:
                    cases.append((asset_class, measurement_type.value, baseline + shift, True))

    detector = IsolationForestDetector()
    trained = detector.train(training)
    if not trained:
        return {"status": "unavailable", "reason": "scikit-learn is not installed"}

    predicted: list[bool] = []
    expected: list[bool] = []
    for asset_class, measurement, value, is_fault in cases:
        predicted.append(detector.score(asset_class, measurement, value) >= 0.5)
        expected.append(is_fault)
    true_positive = sum(actual and guess for actual, guess in zip(expected, predicted, strict=True))
    false_positive = sum(
        not actual and guess for actual, guess in zip(expected, predicted, strict=True)
    )
    false_negative = sum(
        actual and not guess for actual, guess in zip(expected, predicted, strict=True)
    )
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return {
        "status": "measured_on_synthetic_data",
        "cases": len(cases),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }


def main() -> None:
    result = run_evaluation()
    report = (
        "# Detection Evaluation\n\n"
        "Results are measured on synthetic simulator data only; they do not represent "
        "real-world performance.\n\n"
    )
    report += f"```json\n{json.dumps(result, indent=2)}\n```\n"
    output = Path(__file__).resolve().parents[2] / "docs" / "DETECTION_EVALUATION.md"
    output.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
