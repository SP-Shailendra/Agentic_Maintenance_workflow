"""L3 weighted detector ensemble and measurement-based anomaly typing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    score: float
    anomaly_type: str
    triggered: bool
    breakdown: dict[str, float]


class EnsembleDetector:
    def __init__(self, weights: dict[str, float] | None = None, threshold: float = 0.65) -> None:
        self.weights = weights or {"spc": 0.65, "isolation_forest": 0.35}
        self.threshold = threshold

    def combine(self, measurement_scores: dict[str, dict[str, float]]) -> Detection:
        breakdown: dict[str, float] = {}
        for measurement, scores in measurement_scores.items():
            total_weight = sum(self.weights.get(name, 0.0) for name in scores)
            score = (
                sum(value * self.weights.get(name, 0.0) for name, value in scores.items())
                / total_weight
                if total_weight
                else 0.0
            )
            breakdown[measurement] = score
        dominant = (
            max(breakdown, key=lambda measurement: breakdown[measurement])
            if breakdown
            else "unknown"
        )
        anomaly_type = {
            "vibration_rms": "bearing_wear",
            "temperature": "overheat",
            "current": "electrical_load",
            "pressure": "pressure_drop",
        }.get(dominant, "unknown")
        final_score = round(max(breakdown.values(), default=0.0), 6)
        breakdown = {measurement: round(score, 6) for measurement, score in breakdown.items()}
        return Detection(final_score, anomaly_type, final_score >= self.threshold, breakdown)
