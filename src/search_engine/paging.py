from __future__ import annotations

from pathlib import Path

from .document_loader import load_document


def read_text(path: Path) -> str:
    text, _ = load_document(path)
    return text


def split_pages_in_text(text: str) -> list[tuple[int, int, int, str]]:
    if "\f" not in text:
        lines = text.split("\n")
        line_end = max(len(lines), 1)
        return [(1, 1, line_end, "\n".join(lines).strip())]

    pages: list[tuple[int, int, int, str]] = []
    line_cursor = 1
    for page_number, segment in enumerate(text.split("\f"), start=1):
        segment_lines = segment.split("\n")
        if not segment_lines:
            segment_lines = [""]
        line_start = line_cursor
        line_end = line_cursor + len(segment_lines) - 1
        pages.append((page_number, line_start, line_end, "\n".join(segment_lines).strip()))
        line_cursor = line_end + 1
    return pages


def split_pages(path: Path) -> list[tuple[int, int, int, str]]:
    return split_pages_in_text(read_text(path))


def load_page_number(path: Path, page_number: int) -> tuple[int, int, int, str]:
    pages = split_pages(path)
    if not pages:
        return 1, 1, 1, ""
    target_page = max(page_number, 1)
    for current_page, line_start, line_end, text in pages:
        if current_page == target_page:
            return current_page, line_start, line_end, text
    return pages[-1]
