"""L3 three-sigma and two-sided cumulative-sum detector."""

from collections import defaultdict, deque


class SPCDetector:
    def __init__(
        self,
        baseline_size: int = 30,
        threshold: float = 3.0,
        cusum_limit: float = 8.0,
    ) -> None:
        self.baseline_size = baseline_size
        self.threshold = threshold
        self.cusum_limit = cusum_limit
        self._history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=baseline_size)
        )
        self._cusum: dict[tuple[str, str], tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

    def score(self, asset_class: str, measurement_type: str, asset_id: str, value: float) -> float:
        key = (asset_class, measurement_type)
        asset_key = (asset_id, measurement_type)
        history = self._history[key]
        if len(history) < min(10, self.baseline_size):
            history.append(value)
            return 0.0
        center = sum(history) / len(history)
        variance = sum((sample - center) ** 2 for sample in history) / len(history)
        sigma = max(variance**0.5, abs(center) * 0.01, 1e-6)
        z_score = abs(value - center) / sigma
        positive, negative = self._cusum[asset_key]
        positive = max(0.0, positive + (value - center) / sigma - 0.5)
        negative = min(0.0, negative + (value - center) / sigma + 0.5)
        self._cusum[asset_key] = (positive, negative)
        cusum_score = max(positive, abs(negative)) / self.cusum_limit
        history.append(value)
        return min(1.0, max(z_score / self.threshold, cusum_score))