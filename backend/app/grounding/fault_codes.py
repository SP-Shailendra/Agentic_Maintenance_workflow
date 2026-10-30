"""L5 known failure-mode library parsed from the included manual corpus."""

from dataclasses import dataclass
from pathlib import Path

from app.grounding.chunker import ManualChunk, load_manual_corpus


@dataclass(frozen=True)
class FaultCode:
    code: str
    asset_class: str
    document: str
    section: str
    content: str


def parse_fault_codes(directory: Path | None = None) -> dict[str, FaultCode]:
    return {
        chunk.fault_code: FaultCode(
            code=chunk.fault_code,
            asset_class=chunk.asset_class,
            document=chunk.document,
            section=chunk.section,
            content=chunk.content,
        )
        for chunk in load_manual_corpus(directory)
    }


def fault_code_from_chunk(chunk: ManualChunk) -> FaultCode:
    return FaultCode(
        chunk.fault_code, chunk.asset_class, chunk.document, chunk.section, chunk.content
    )
