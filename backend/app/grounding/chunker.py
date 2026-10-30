"""L5 section-aware chunking for the local synthetic maintenance corpus."""

import re
from dataclasses import dataclass
from pathlib import Path

ASSET_CLASS_BY_FILE = {
    "wire_draw_motor.md": "wire_draw_motor",
    "testcell_generator.md": "testcell_generator",
    "imaging_chiller.md": "imaging_chiller",
}
SECTION_PATTERN = re.compile(r"^##\s+([^\n]+)\n(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
FAULT_PATTERN = re.compile(r"\b([A-Z]{2}-\d{3})\b")


@dataclass(frozen=True)
class ManualChunk:
    asset_class: str
    fault_code: str
    document: str
    section: str
    content: str


def chunk_manual(path: Path) -> list[ManualChunk]:
    """Split one manual into fault-code sections with source metadata."""
    asset_class = ASSET_CLASS_BY_FILE.get(path.name)
    if asset_class is None:
        raise ValueError(f"Unknown manual asset class: {path.name}")
    text = path.read_text(encoding="utf-8")
    chunks: list[ManualChunk] = []
    for heading, content in SECTION_PATTERN.findall(text):
        code = FAULT_PATTERN.search(heading)
        if code:
            chunks.append(
                ManualChunk(
                    asset_class=asset_class,
                    fault_code=code.group(1),
                    document=path.name,
                    section=heading.strip(),
                    content=content.strip(),
                )
            )
    return chunks


def load_manual_corpus(directory: Path | None = None) -> list[ManualChunk]:
    root = directory or Path(__file__).resolve().parents[3] / "data" / "manuals"
    return [chunk for path in sorted(root.glob("*.md")) for chunk in chunk_manual(path)]
