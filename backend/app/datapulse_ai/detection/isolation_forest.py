"""L3 per-asset-class and per-measurement Isolation Forest detector."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.datapulse_ai.model_store import ModelStore


class IsolationForestDetector:
    def __init__(self, model_store: ModelStore | None = None, *, seed: int = 17) -> None:
        self.model_store = model_store
        self.seed = seed
        self._models: dict[tuple[str, str], tuple[Any, float, float, float, float, float]] = {}
        self.available = True

    def train(self, training: Mapping[tuple[str, str], Iterable[float]]) -> bool:
        try:
            import numpy as np
            from sklearn.ensemble import IsolationForest
        except ImportError:
            self.available = False
            return False
        for key, values in training.items():
            samples = np.asarray(list(values), dtype=float).reshape(-1, 1)
            if len(samples) < 10:
                continue
            model = IsolationForest(
                n_estimators=100,
                contamination="auto",
                random_state=self.seed,
            ).fit(samples)
            scores = model.decision_function(samples)
            score_cutoff = float(np.quantile(scores, 0.001))
            score_scale = max(float(np.quantile(scores, 0.99)) - score_cutoff, 1e-9)
            value_min = float(samples.min())
            value_max = float(samples.max())
            value_scale = max(
                float(np.quantile(samples, 0.99) - np.quantile(samples, 0.01)),
                abs(float(np.median(samples))) * 0.01,
                1e-9,
            )
            self._models[key] = (
                model,
                score_cutoff,
                score_scale,
                value_min,
                value_max,
                value_scale,
            )
            if self.model_store is not None:
                self.model_store.save(
                    f"isolation-forest-{key[0]}-{key[1]}",
                    model,
                    {
                        "asset_class": key[0],
                        "measurement_type": key[1],
                        "sample_count": len(samples),
                        "seed": self.seed,
                        "score_cutoff": score_cutoff,
                        "value_min": value_min,
                        "value_max": value_max,
                        "value_scale": value_scale,
                    },
                )
        self.available = bool(self._models)
        return self.available

    def score(self, asset_class: str, measurement_type: str, value: float) -> float:
        if not self.available or (asset_class, measurement_type) not in self._models:
            return 0.0
        (
            model,
            score_cutoff,
            score_scale,
            value_min,
            value_max,
            value_scale,
        ) = self._models[(asset_class, measurement_type)]
        raw_score = float(model.decision_function([[value]])[0])
        forest_score = (score_cutoff - raw_score) / score_scale
        range_score = max(value_min - value, value - value_max, 0.0) / value_scale
        return round(max(0.0, min(1.0, max(forest_score, range_score))), 6)
