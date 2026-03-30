from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SearchResult:
    source_root_id: int
    source_path: str
    document_id: int
    content_unit_id: int
    document_path: str
    filename: str
    unit_type: str
    page_number: int | None
    section_name: str
    display_text: str
    score: float


@dataclass(slots=True)
class SearchResponse:
    results: list[SearchResult]
    warning: str | None = None
