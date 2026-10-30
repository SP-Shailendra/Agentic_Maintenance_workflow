"""L5 fail-closed diagnosis verification against retrieved manual passages."""

from app.grounding.chunker import ManualChunk
from app.schemas.domain import DiagnosisResult


def validate_diagnosis(
    diagnosis: DiagnosisResult,
    retrieved: list[ManualChunk],
    known_failure_modes: set[str],
    *,
    unverified_confidence_cap: float = 0.49,
) -> DiagnosisResult:
    verified_candidates = []
    for candidate in diagnosis.candidates:
        matching_code = candidate.failure_mode in known_failure_modes
        matching_citation = any(
            citation.document == chunk.document
            and citation.section == chunk.section
            and citation.passage.strip()
            and citation.passage.strip() in chunk.content
            for citation in candidate.citations
            for chunk in retrieved
        )
        verified = matching_code and matching_citation
        rationale = candidate.rationale
        if not matching_code:
            rationale += " Unverified: failure mode is absent from the manual fault-code library."
        if not matching_citation:
            rationale += (
                " Unverified: no citation passage exactly matches retrieved manual content."
            )
        verified_candidates.append(
            candidate.model_copy(
                update={
                    "verified": verified,
                    "confidence": candidate.confidence
                    if verified
                    else min(candidate.confidence, unverified_confidence_cap),
                    "rationale": rationale,
                }
            )
        )
    return diagnosis.model_copy(update={"candidates": verified_candidates})
