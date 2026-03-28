from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DocumentRecord:
    path: Path
    content_hash: str


@dataclass(slots=True)
class SearchHit:
    content_hash: str
    file_path: str
    relative_path: str
    page_number: int
    snippet: str
    score: float
