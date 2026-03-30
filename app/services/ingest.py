from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.global_store import utc_now
from app.config import get_settings
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
    ".xlsx",
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
    except Exception as exc:
        raise RuntimeError(
            "Docling is required for ingestion but is not available in the worker environment."
        ) from exc

    try:
        converter = DocumentConverter()
        result = converter.convert(str(document_path))
    except Exception as exc:
        raise RuntimeError(f"Docling failed to parse {document_path.name}: {exc}") from exc

    markdown = extract_markdown(result)
    if not markdown.strip():
        raise RuntimeError(f"Docling returned no extractable text for {document_path.name}.")

    units = extract_structured_units(result.document, markdown)
    if units:
        return units

    raise RuntimeError(f"Docling produced no structured content for {document_path.name}.")


def extract_markdown(result: object) -> str:
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError("Docling result did not include a document object.")

    export_to_markdown = getattr(document, "export_to_markdown", None)
    if callable(export_to_markdown):
        markdown = export_to_markdown()
        if isinstance(markdown, str):
            return markdown

    export_to_text = getattr(document, "export_to_text", None)
    if callable(export_to_text):
        text = export_to_text()
        if isinstance(text, str):
            return text

    text = str(document)
    return text if isinstance(text, str) else ""


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

    if not units:
        body = "\n".join(line for line in lines if line.strip()).strip()
        if body:
            units.append(
                ParsedUnit(
                    unit_type="section",
                    page_number=1,
                    section_name="Document",
                    anchor_key="section-1",
                    text_content=body,
                    caption="",
                    display_text=body,
                )
            )
    return units


def extract_structured_units(doc: Any, fallback_markdown: str) -> list[ParsedUnit]:
    units: list[ParsedUnit] = []
    current_section = "Document"
    seen_refs: set[str] = set()
    iterate_items = getattr(doc, "iterate_items", None)

    if callable(iterate_items):
        for item, _level in iterate_items(
            root=getattr(doc, "body", None),
            with_groups=False,
            traverse_pictures=True,
        ):
            item_ref = str(getattr(item, "self_ref", id(item)))
            if item_ref in seen_refs:
                continue
            seen_refs.add(item_ref)

            label = item_label(item)
            page_number = page_number_from_item(item)

            if label in {"title", "section_header"}:
                heading = text_from_item(item)
                if heading:
                    current_section = heading
                    units.append(
                        ParsedUnit(
                            unit_type="section",
                            page_number=page_number,
                            section_name=heading,
                            anchor_key=anchor_from_ref(item_ref),
                            text_content=heading,
                            caption="",
                            display_text=heading,
                        )
                    )
                continue

            if label in {
                "paragraph",
                "text",
                "list_item",
                "formula",
                "code",
                "caption",
                "page_header",
                "page_footer",
            }:
                body = text_from_item(item)
                if body:
                    units.append(
                        ParsedUnit(
                            unit_type="section",
                            page_number=page_number,
                            section_name=current_section,
                            anchor_key=anchor_from_ref(item_ref),
                            text_content=body,
                            caption="",
                            display_text=body,
                        )
                    )
                continue

            if label in {"picture", "chart"}:
                caption = caption_from_item(item, doc)
                picture_text = markdown_from_item(item, doc)
                display = build_display_text(caption, picture_text, fallback=f"Figure in {current_section}")
                units.append(
                    ParsedUnit(
                        unit_type="figure",
                        page_number=page_number,
                        section_name=current_section,
                        anchor_key=anchor_from_ref(item_ref),
                        text_content=picture_text,
                        caption=caption,
                        display_text=display,
                    )
                )
                continue

            if label == "table":
                caption = caption_from_item(item, doc)
                table_text = table_text_from_item(item, doc)
                display = build_display_text(caption, table_text, fallback=f"Table in {current_section}")
                units.append(
                    ParsedUnit(
                        unit_type="table",
                        page_number=page_number,
                        section_name=current_section,
                        anchor_key=anchor_from_ref(item_ref),
                        text_content=table_text,
                        caption=caption,
                        display_text=display,
                    )
                )

    if units:
        return units
    return split_sections(fallback_markdown)


def item_label(item: Any) -> str:
    label = getattr(item, "label", "")
    value = getattr(label, "value", label)
    return str(value).lower()


def text_from_item(item: Any) -> str:
    for attr in ("text", "orig", "name"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def caption_from_item(item: Any, doc: Any) -> str:
    caption_text = getattr(item, "caption_text", None)
    if callable(caption_text):
        try:
            caption = caption_text(doc)
            if isinstance(caption, str):
                return caption.strip()
        except Exception:
            return ""
    return ""


def markdown_from_item(item: Any, doc: Any) -> str:
    export_to_markdown = getattr(item, "export_to_markdown", None)
    if callable(export_to_markdown):
        try:
            value = export_to_markdown(doc)
            if isinstance(value, str):
                return value.strip()
        except Exception:
            return ""
    return ""


def table_text_from_item(item: Any, doc: Any) -> str:
    export_to_dataframe = getattr(item, "export_to_dataframe", None)
    if callable(export_to_dataframe):
        try:
            dataframe = export_to_dataframe(doc)
            to_markdown = getattr(dataframe, "to_markdown", None)
            if callable(to_markdown):
                try:
                    return str(to_markdown(index=False)).strip()
                except Exception:
                    pass
            to_csv = getattr(dataframe, "to_csv", None)
            if callable(to_csv):
                try:
                    return str(to_csv(index=False)).strip()
                except Exception:
                    pass
        except Exception:
            pass
    return markdown_from_item(item, doc)


def page_number_from_item(item: Any) -> int | None:
    prov = getattr(item, "prov", None)
    if not prov:
        return None
    try:
        pages = [int(getattr(entry, "page_no")) for entry in prov if getattr(entry, "page_no", None) is not None]
    except Exception:
        return None
    return min(pages) if pages else None


def anchor_from_ref(item_ref: str) -> str:
    anchor = re.sub(r"[^a-zA-Z0-9_-]+", "-", item_ref).strip("-")
    return anchor or "item"


def build_display_text(caption: str, body: str, fallback: str) -> str:
    if caption and body:
        return f"{caption}\n\n{body}".strip()
    if caption:
        return caption
    if body:
        return body
    return fallback


def build_units(parsed_units: list[ParsedUnit]) -> list[dict[str, object]]:
    settings = get_settings()
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
                "embedding_model": settings.vector_model_name,
                "created_at": utc_now(),
            }
        )
    return units
