"""L5 asset-class-filtered retrieval with a keyword/BM25-style fallback."""

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.grounding.chunker import ManualChunk, load_manual_corpus

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: ManualChunk
    score: float


class ManualRetriever:
    def __init__(self, chunks: list[ManualChunk] | None = None) -> None:
        self.chunks = chunks or load_manual_corpus()

    def retrieve(self, query: str, asset_class: str, top_k: int = 5) -> list[RetrievedChunk]:
        eligible = [chunk for chunk in self.chunks if chunk.asset_class == asset_class]
        query_tokens = TOKEN_PATTERN.findall(query.lower())
        if not eligible or not query_tokens:
            return []
        document_tokens = [TOKEN_PATTERN.findall(chunk.content.lower()) for chunk in eligible]
        document_frequency = Counter(token for tokens in document_tokens for token in set(tokens))
        scored: list[RetrievedChunk] = []
        for chunk, tokens in zip(eligible, document_tokens, strict=True):
            counts = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                frequency = counts[token]
                if frequency:
                    inverse_document_frequency = math.log1p(
                        len(eligible) / (1 + document_frequency[token])
                    )
                    score += (frequency / (frequency + 1.2)) * inverse_document_frequency
            if score:
                scored.append(RetrievedChunk(chunk, score))
        return sorted(scored, key=lambda result: result.score, reverse=True)[:top_k]
