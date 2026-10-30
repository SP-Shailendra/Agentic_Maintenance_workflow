"""L2 rolling sensor statistics and optional vibration FFT peaks."""

from collections import defaultdict, deque
from math import sqrt
from statistics import mean, pstdev
from typing import Any

from app.schemas.domain import MeasurementType, TelemetryReading


class FeatureEngine:
    WINDOWS_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "60m": 3600}

    def __init__(self, sample_interval_seconds: float = 5.0) -> None:
        self.sample_interval_seconds = sample_interval_seconds
        self._series: dict[
            tuple[str, MeasurementType], deque[TelemetryReading]
        ] = defaultdict(deque)
        self._previous: dict[tuple[str, MeasurementType], float] = {}

    def add(
        self,
        reading: TelemetryReading,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = (reading.asset_id, reading.measurement_type)
        series = self._series[key]
        series.append(reading)
        maximum = max(self.WINDOWS_SECONDS.values())
        while (
            series
            and (reading.timestamp_utc - series[0].timestamp_utc).total_seconds() > maximum
        ):
            series.popleft()
        values = [sample.value for sample in series]
        features: dict[str, Any] = {
            "asset_id": reading.asset_id,
            "measurement_type": reading.measurement_type.value,
            "timestamp_utc": reading.timestamp_utc,
            "context": context or {},
            "windows": {},
        }
        for name, duration in self.WINDOWS_SECONDS.items():
            window_values = [
                sample.value
                for sample in series
                if (reading.timestamp_utc - sample.timestamp_utc).total_seconds() <= duration
            ]
            if not window_values:
                continue
            features["windows"][name] = {
                "mean": mean(window_values),
                "std": pstdev(window_values),
                "min": min(window_values),
                "max": max(window_values),
                "rms": sqrt(sum(value * value for value in window_values) / len(window_values)),
                "rate_of_change": window_values[-1] - window_values[0],
            }
        prior = self._previous.get(key)
        features["rate_per_second"] = (
            (reading.value - prior) / self.sample_interval_seconds if prior is not None else 0.0
        )
        self._previous[key] = reading.value
        if reading.measurement_type == MeasurementType.VIBRATION_RMS:
            features["fft_peaks"] = self._fft_peaks(values, self.sample_interval_seconds)
        return features

    @staticmethod
    def _fft_peaks(
        values: list[float],
        sample_interval_seconds: float,
        top_n: int = 3,
    ) -> list[dict[str, float]]:
        if len(values) < 4:
            return []
        try:
            import numpy as np
        except ImportError:
            return []
        samples = np.asarray(values)
        spectrum = np.abs(np.fft.rfft(samples - np.mean(samples)))
        frequencies = np.fft.rfftfreq(len(values), d=sample_interval_seconds)
        indices = sorted(
            range(1, len(spectrum)),
            key=lambda index: spectrum[index],
            reverse=True,
        )[:top_n]
        return [
            {"frequency_hz": float(frequencies[index]), "magnitude": float(spectrum[index])}
            for index in indices
        ]


def health_index(detector_scores: list[float]) -> float:
    """Map mean detector anomaly score to a bounded 0-100 equipment health index."""
    if not detector_scores:
        return 100.0
    return round(max(0.0, min(100.0, 100 * (1 - sum(detector_scores) / len(detector_scores)))), 1)