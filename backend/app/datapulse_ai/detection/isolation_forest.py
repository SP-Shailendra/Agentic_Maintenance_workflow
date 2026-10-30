"""L3 per-asset-class and per-measurement Isolation Forest detector."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.datapulse_ai.model_store import ModelStore


class IsolationForestDetector:
    def __init__(self, model_store: ModelStore | None = None, *, seed: int = 17) -> None:
        self.model_store = model_store
        self.seed = seed
        self._models: dict[tuple[str, str], tuple[Any, float, float]] = {}
        self.available = True

    def train(self, training: dict[tuple[str, str], Iterable[float]]) -> bool:
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
            score_min = float(scores.min())
            score_max = float(scores.max())
            self._models[key] = (model, score_min, score_max)
            if self.model_store is not None:
                self.model_store.save(
                    f"isolation-forest-{key[0]}-{key[1]}",
                    model,
                    {
                        "asset_class": key[0],
                        "measurement_type": key[1],
                        "sample_count": len(samples),
                        "seed": self.seed,
                    },
                )
        self.available = bool(self._models)
        return self.available

    def score(self, asset_class: str, measurement_type: str, value: float) -> float:
        if not self.available or (asset_class, measurement_type) not in self._models:
            return 0.0
        model, score_min, score_max = self._models[(asset_class, measurement_type)]
        raw_score = float(model.decision_function([[value]])[0])
        span = max(score_max - score_min, 1e-9)
        return round(max(0.0, min(1.0, (score_max - raw_score) / span)), 6)