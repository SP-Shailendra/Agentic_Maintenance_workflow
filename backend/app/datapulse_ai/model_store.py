"""L3 persistence for versioned detector models and training metadata."""

import hashlib
import json
from pathlib import Path
from typing import Any


class ModelStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def version_hash(metadata: dict[str, Any]) -> str:
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def save(self, name: str, model: Any, metadata: dict[str, Any]) -> str:
        try:
            import joblib
        except ImportError as error:
            raise RuntimeError("joblib is required to persist trained detector models") from error
        self.directory.mkdir(parents=True, exist_ok=True)
        version = self.version_hash(metadata)
        joblib.dump(
            {"model": model, "metadata": metadata, "version": version},
            self.directory / f"{name}.joblib",
        )
        return version

    def load(self, name: str) -> tuple[Any, dict[str, Any], str] | None:
        path = self.directory / f"{name}.joblib"
        if not path.exists():
            return None
        try:
            import joblib
        except ImportError as error:
            raise RuntimeError("joblib is required to load trained detector models") from error
        record = joblib.load(path)
        if record["version"] != self.version_hash(record["metadata"]):
            raise ValueError(f"Model metadata hash mismatch: {path.name}")
        return record["model"], record["metadata"], record["version"]
