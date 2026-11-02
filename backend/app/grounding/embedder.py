"""L5 optional local fastembed wrapper; callers retain keyword retrieval fallback."""

from typing import Any


class LocalEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self.model_name = model_name
        self._model: Any | None = None

    @property
    def available(self) -> bool:
        return self._model is not None

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        try:
            from fastembed import TextEmbedding
        except ImportError:
            return None
        if self._model is None:
            self._model = TextEmbedding(model_name=self.model_name)
        return [vector.tolist() for vector in self._model.embed(texts)]
