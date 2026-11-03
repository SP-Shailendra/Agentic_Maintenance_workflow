"""L3 three-sigma and two-sided cumulative-sum detector."""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping


class SPCDetector:
    def __init__(
        self,
        baseline_size: int = 30,
        threshold: float = 5.0,
        cusum_limit: float = 30.0,
        cusum_reference_value: float = 1.5,
        operating_cycle_ticks: int = 120,
    ) -> None:
        self.baseline_size = baseline_size
        self.threshold = threshold
        self.cusum_limit = cusum_limit
        self.cusum_reference_value = cusum_reference_value
        self.operating_cycle_ticks = max(1, operating_cycle_ticks)
        self._history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=baseline_size)
        )
        self._cusum: dict[tuple[str, str], tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))
        self._phase_profiles: dict[tuple[str, str], tuple[float, ...]] = {}

    def score(
        self,
        asset_class: str,
        measurement_type: str,
        asset_id: str,
        value: float,
        *,
        cycle_tick: int | None = None,
    ) -> float:
        key = (asset_id, measurement_type)
        profile = self._phase_profiles.get(key)
        if profile:
            phase = 0 if cycle_tick is None else cycle_tick
            value -= profile[phase % len(profile)]
        history = self._history[key]
        if len(history) < min(10, self.baseline_size):
            history.append(value)
            return 0.0
        center = sum(history) / len(history)
        variance = sum((sample - center) ** 2 for sample in history) / len(history)
        sigma = max(variance**0.5, abs(center) * 0.01, 1e-6)
        z_score = abs(value - center) / sigma
        positive, negative = self._cusum[key]
        positive = max(
            0.0,
            positive + (value - center) / sigma - self.cusum_reference_value,
        )
        negative = min(
            0.0,
            negative + (value - center) / sigma + self.cusum_reference_value,
        )
        self._cusum[key] = (positive, negative)
        cusum_score = max(positive, abs(negative)) / self.cusum_limit
        history.append(value)
        return min(1.0, max(z_score / self.threshold, cusum_score))

    def fit(
        self,
        baselines: Mapping[tuple[str, str], Iterable[float]],
        *,
        phase_profiles: Mapping[tuple[str, str], Iterable[float]] | None = None,
    ) -> None:
        """Preload per-asset SPC histories from healthy reference samples."""
        self._history.clear()
        self._cusum.clear()
        self._phase_profiles.clear()
        for key, values in baselines.items():
            samples = list(values)
            supplied_profile = phase_profiles.get(key) if phase_profiles is not None else None
            if supplied_profile is not None:
                profile_samples = list(supplied_profile)
                if len(profile_samples) < self.operating_cycle_ticks:
                    raise ValueError("phase profile must cover a full operating cycle")
                profile = tuple(
                    sum(profile_samples[phase :: self.operating_cycle_ticks])
                    / len(profile_samples[phase :: self.operating_cycle_ticks])
                    for phase in range(self.operating_cycle_ticks)
                )
                self._phase_profiles[key] = profile
            elif len(samples) >= self.operating_cycle_ticks:
                profile = tuple(
                    sum(samples[phase :: self.operating_cycle_ticks])
                    / len(samples[phase :: self.operating_cycle_ticks])
                    for phase in range(self.operating_cycle_ticks)
                )
                self._phase_profiles[key] = profile
            if self.operating_cycle_ticks and key in self._phase_profiles:
                profile = self._phase_profiles[key]
                samples = [
                    value - profile[index % self.operating_cycle_ticks]
                    for index, value in enumerate(samples)
                ]
            if len(samples) > self.baseline_size > 1:
                last_index = len(samples) - 1
                samples = [
                    samples[index * last_index // (self.baseline_size - 1)]
                    for index in range(self.baseline_size)
                ]
            self._history[key].extend(samples[-self.baseline_size :])
