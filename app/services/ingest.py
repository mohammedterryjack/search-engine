from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
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

DATA_IMAGE_RE = re.compile(
    r"data:(?P<mime>image/[^;]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)", re.IGNORECASE
)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)", re.IGNORECASE)
HTML_IMAGE_RE = re.compile(r"<img[^>]*>", re.IGNORECASE)


def extract_image_data(text: str) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    match = DATA_IMAGE_RE.search(text)
    if not match:
        return None, None
    data = "".join(match.group("data").split())
    mime = match.group("mime")
    if not data:
        return None, None
    return mime, data


def strip_image_markup(text: str) -> str:
    if not text:
        return ""
    cleaned = MARKDOWN_IMAGE_RE.sub(" ", text)
    cleaned = HTML_IMAGE_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


@lru_cache(maxsize=1)
def build_docling_converter():
    try:
        from docling.datamodel.document import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except Exception as exc:
        raise RuntimeError(
            "Docling is required for ingestion but is not available in the worker environment."
        ) from exc

    pipeline_options = None
    try:
        from docling.pipeline.standard_pdf_pipeline import ThreadedPdfPipelineOptions

        pipeline_options = ThreadedPdfPipelineOptions(generate_picture_images=True)
    except Exception:
        try:
            from docling.datamodel.pipeline_options import PdfPipelineOptions

            pipeline_options = PdfPipelineOptions(generate_picture_images=True)
        except Exception:
            pipeline_options = None

    format_options: dict[InputFormat, PdfFormatOption] = {}
    if pipeline_options is not None:
        format_options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pipeline_options)

    return DocumentConverter(format_options=format_options) if format_options else DocumentConverter()


@dataclass(slots=True)
class ParsedUnit:
    unit_type: str
    page_number: int | None
    section_name: str
    anchor_key: str
    text_content: str
    caption: str
    display_text: str
    image_mime: str | None = None
    image_data: str | None = None


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
    converter = build_docling_converter()
    try:
        result = converter.convert(str(document_path))
    except Exception as exc:
        raise RuntimeError(f"Docling failed to parse {document_path.name}: {exc}") from exc

    markdown = extract_markdown(result)
    if not markdown.strip():
        raise RuntimeError(f"Docling returned no extractable text for {document_path.name}.")

    units = extract_structured_units(result.document)
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



def extract_structured_units(doc: Any) -> list[ParsedUnit]:
    units: list[ParsedUnit] = []
    current_section = "Document"
    current_section_anchor: str | None = None
    section_page: int | None = None
    section_buffer: list[str] = []
    seen_refs: set[str] = set()
    iterate_items = getattr(doc, "iterate_items", None)
    section_counter = 0

    def flush_section() -> None:
        nonlocal section_buffer, section_page, current_section_anchor, section_counter
        body = "\n\n".join(line for line in section_buffer if line.strip()).strip()
        if not body:
            section_buffer = []
            section_page = None
            return
        section_counter += 1
        anchor = current_section_anchor or f"section-{section_counter}"
        units.append(
            ParsedUnit(
                unit_type="section",
                page_number=section_page,
                section_name=current_section,
                anchor_key=anchor,
                text_content=body,
                caption="",
                display_text=body,
            )
        )
        section_buffer = []
        section_page = None
        current_section_anchor = None

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
                    flush_section()
                    current_section = heading
                    current_section_anchor = anchor_from_ref(item_ref)
                    section_page = page_number
                    section_buffer = [heading]
                continue

            if label in {
                "paragraph",
                "text",
                "list_item",
                "formula",
                "code",
                "caption",
            }:
                body = text_from_item(item)
                if body:
                    if not section_buffer:
                        current_section_anchor = current_section_anchor or anchor_from_ref(item_ref)
                        section_page = section_page or page_number
                    section_buffer.append(body)
                continue

            if label in {"picture", "chart"}:
                caption = caption_from_item(item, doc)
                picture_text = markdown_from_item(item, doc)
                cleaned_picture_text = strip_image_markup(picture_text)
                image_mime, image_data = extract_image_data(picture_text)
                display = build_display_text(
                    caption,
                    cleaned_picture_text,
                    fallback=f"Figure in {current_section}",
                )
                units.append(
                    ParsedUnit(
                        unit_type="figure",
                        page_number=page_number,
                        section_name=current_section,
                        anchor_key=anchor_from_ref(item_ref),
                        text_content=display,
                        caption=caption,
                        display_text=display,
                        image_mime=image_mime,
                        image_data=image_data,
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

    flush_section()
    return _merge_sections(units)


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
                "image_mime": unit.image_mime,
                "image_data": unit.image_data,
            }
        )
    return units


def _merge_sections(units: list[ParsedUnit]) -> list[ParsedUnit]:
    merged: list[ParsedUnit] = []
    prev: ParsedUnit | None = None
    prev_key: str | None = None
    for unit in units:
        if unit.unit_type != "section":
            merged.append(unit)
            prev = None
            prev_key = None
            continue
        key = _normalize_section_name(unit.section_name)
        if prev is not None and prev_key == key:
            prev.text_content = _join_text(prev.text_content, unit.text_content)
            prev.display_text = _join_text(prev.display_text, unit.display_text)
            prev.caption = _join_text(prev.caption, unit.caption)
            prev.anchor_key = prev.anchor_key or unit.anchor_key
            continue
        merged.append(unit)
        prev = unit
        prev_key = key
    return merged


def _normalize_section_name(section_name: str) -> str:
    candidate = re.sub(r"^[\d\s\.)-:,]+", "", section_name or "", flags=re.UNICODE)
    collapsed = re.sub(r"\s+", " ", candidate).strip().lower()
    if not collapsed:
        return ""
    if "reference" in collapsed or "bibliograph" in collapsed:
        return "references"
    return collapsed


def _join_text(existing: str, addition: str) -> str:
    if not existing:
        return addition
    if not addition:
        return existing
    return f"{existing}\n\n{addition}"
