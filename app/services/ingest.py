from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db.global_store import utc_now
from app.services.tokenize import term_frequencies


SUPPORTED_EXTENSIONS = {
    ".csv",
    ".docx",
    ".html",
    ".jpeg",
    ".jpg",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".txt",
    ".xlsx",
    ".xml",
}


@dataclass(slots=True)
class ParsedUnit:
    unit_type: str
    page_number: int | None
    section_name: str
    anchor_key: str
    text_content: str
    caption: str
    display_text: str


def list_supported_documents(source_path: Path) -> list[Path]:
    if source_path.is_file():
        return [source_path] if source_path.suffix.lower() in SUPPORTED_EXTENSIONS else []
    paths = [
        path
        for path in source_path.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(paths)


def parse_document(document_path: Path) -> list[ParsedUnit]:
    try:
        from docling.document_converter import DocumentConverter  # type: ignore

        converter = DocumentConverter()
        result = converter.convert(str(document_path))
        text = getattr(result.document, "export_to_markdown", lambda: "")()
        if not text:
            text = str(result.document)
        sections = split_sections(text)
        if sections:
            return sections
    except Exception:
        pass
    return fallback_parse(document_path)


def split_sections(text: str) -> list[ParsedUnit]:
    lines = [line.rstrip() for line in text.splitlines()]
    units: list[ParsedUnit] = []
    current_heading = "Document"
    current_lines: list[str] = []
    counter = 0

    def flush() -> None:
        nonlocal counter
        body = "\n".join(line for line in current_lines if line.strip()).strip()
        if not body:
            return
        counter += 1
        units.append(
            ParsedUnit(
                unit_type="section",
                page_number=None,
                section_name=current_heading,
                anchor_key=f"section-{counter}",
                text_content=body,
                caption="",
                display_text=body,
            )
        )

    for line in lines:
        if line.startswith("#"):
            flush()
            current_lines = []
            current_heading = line.lstrip("# ").strip() or "Section"
            continue
        current_lines.append(line)
    flush()
    return units


def fallback_parse(document_path: Path) -> list[ParsedUnit]:
    try:
        raw_text = document_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        raise RuntimeError(f"Could not read {document_path.name}: {exc}") from exc
    body = raw_text.strip()
    if not body:
        body = f"{document_path.name} contains no extractable text."
    return [
        ParsedUnit(
            unit_type="section",
            page_number=1,
            section_name=document_path.stem,
            anchor_key="section-1",
            text_content=body,
            caption="",
            display_text=body,
        )
    ]


def build_units(parsed_units: list[ParsedUnit]) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    for unit in parsed_units:
        terms = term_frequencies(unit.display_text)
        units.append(
            {
                "unit_type": unit.unit_type,
                "page_number": unit.page_number,
                "section_name": unit.section_name,
                "anchor_key": unit.anchor_key,
                "text_content": unit.text_content,
                "caption": unit.caption,
                "display_text": unit.display_text,
                "token_count": sum(terms.values()),
                "terms": dict(terms),
                "created_at": utc_now(),
            }
        )
    return units
