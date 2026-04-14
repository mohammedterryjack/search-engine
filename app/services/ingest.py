from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.db.global_store import utc_now
from app.config import get_settings
from app.env import require_env
from app.services.content_units import compose_text_content
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
    """Extract and downscale image data from markdown base64 strings.

    Downscales images to max 800px width to reduce database size and improve UI performance.
    """
    if not text:
        return None, None
    match = DATA_IMAGE_RE.search(text)
    if not match:
        return None, None
    data = "".join(match.group("data").split())
    mime = match.group("mime")
    if not data:
        return None, None

    # Downscale image to reduce database size
    try:
        import base64
        from io import BytesIO
        from PIL import Image

        # Decode base64 to image
        image_bytes = base64.b64decode(data)
        image = Image.open(BytesIO(image_bytes))

        # Downscale if wider than 800px
        max_width = 800
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

        # Re-encode to base64
        buffer = BytesIO()
        image_format = image.format or 'PNG'
        image.save(buffer, format=image_format, optimize=True, quality=85)
        downscaled_data = base64.b64encode(buffer.getvalue()).decode('utf-8')

        return mime, downscaled_data
    except Exception as exc:
        raise RuntimeError("Failed to decode or downscale embedded image data.") from exc


def strip_image_markup(text: str) -> str:
    if not text:
        return ""
    cleaned = MARKDOWN_IMAGE_RE.sub(" ", text)
    cleaned = HTML_IMAGE_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def generate_image_caption(image_data: str) -> str:
    """Generate caption for an image using Ollama's llava model.

    Args:
        image_data: Base64-encoded image data (without the data URI prefix)

    Returns:
        Generated caption text, or empty string if captioning fails
    """
    try:
        ollama_url = require_env("OLLAMA_URL").rstrip("/")

        payload = {
            "model": "llava",
            "messages": [
                {
                    "role": "user",
                    "content": "Describe this image in one concise sentence suitable as a figure caption.",
                    "images": [image_data]
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 100,
            }
        }

        request = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("error"):
            return ""

        message = data.get("message", {})
        caption = str(message.get("content", "")).strip() if isinstance(message, dict) else ""
        return caption

    except Exception:
        # Silently fail - captioning is optional enhancement
        return ""


# Global singleton converter to prevent OCR models from reloading on each document
_GLOBAL_CONVERTER = None


def build_docling_converter():
    """Build or return existing DocumentConverter with memory-optimized settings.

    Uses a global singleton to reuse OCR model instances across documents.
    Without this, RapidOCR reloads 770 weights on every document causing OOM.
    """
    global _GLOBAL_CONVERTER

    if _GLOBAL_CONVERTER is not None:
        return _GLOBAL_CONVERTER

    try:
        from docling.datamodel.document import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import RapidOcrOptions
    except Exception as exc:
        raise RuntimeError(
            "Docling is required for ingestion but is not available in the worker environment."
        ) from exc

    # Configure RapidOCR with ONNX Runtime backend and thread settings
    # backend="onnxruntime": Force ONNX Runtime instead of PyTorch (PyTorch loads 770 weights per doc)
    # EngineConfig.onnxruntime.intra_op_num_threads: threads within each operator (default -1 uses all cores)
    rapidocr_options = RapidOcrOptions(
        backend="onnxruntime",
        rapidocr_params={
            "EngineConfig.onnxruntime.intra_op_num_threads": 4,
        }
    )

    try:
        from docling.pipeline.standard_pdf_pipeline import ThreadedPdfPipelineOptions
    except Exception as exc:
        raise RuntimeError(
            "Docling ThreadedPdfPipelineOptions is required but unavailable."
        ) from exc

    # Memory optimization settings:
    # - images_scale=1.0: Reduce from default 2.0 (Issue #3216)
    # - generate_parsed_pages=False: Don't keep parsed pages in memory (Issue #2540)
    # - generate_page_images=False: Skip page image generation to save memory
    # - generate_picture_images=True: Extract pictures for figure display
    # - ocr_options: Configure RapidOCR threading
    pipeline_options = ThreadedPdfPipelineOptions(
        generate_picture_images=True,
        images_scale=1.0,
        generate_parsed_pages=False,
        generate_page_images=False,
        ocr_options=rapidocr_options,
    )

    format_options: dict[InputFormat, PdfFormatOption] = {}
    format_options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pipeline_options)

    _GLOBAL_CONVERTER = DocumentConverter(format_options=format_options)
    return _GLOBAL_CONVERTER


@dataclass(slots=True)
class ParsedUnit:
    unit_type: str
    page_number: int | None
    section_name: str
    anchor_key: str
    text_content: str
    caption: str
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
    """Parse document and return units as a list."""
    converter = build_docling_converter()
    try:
        result = converter.convert(str(document_path))
    except Exception as exc:
        raise RuntimeError(f"Docling failed to parse {document_path.name}: {exc}") from exc

    markdown = extract_markdown(result)
    if not markdown.strip():
        raise RuntimeError(f"Docling returned no extractable text for {document_path.name}.")

    units = extract_structured_units(result.document)

    # Free memory from docling result
    del result
    del markdown

    if units:
        return units

    raise RuntimeError(f"Docling produced no structured content for {document_path.name}.")


def extract_markdown(result: object) -> str:
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError("Docling result did not include a document object.")

    export_to_markdown = getattr(document, "export_to_markdown", None)
    if not callable(export_to_markdown):
        raise RuntimeError("Docling document does not expose export_to_markdown().")
    markdown = export_to_markdown()
    if not isinstance(markdown, str):
        raise RuntimeError("Docling export_to_markdown() did not return text.")
    return markdown



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

                # If no text or caption, try generating caption from image with llava
                if not cleaned_picture_text.strip() and not caption.strip() and image_data:
                    caption = generate_image_caption(image_data)

                # Skip if still no content after captioning attempt
                if not cleaned_picture_text.strip() and not caption.strip():
                    continue

                units.append(
                    ParsedUnit(
                        unit_type="figure",
                        page_number=page_number,
                        section_name=current_section,
                        anchor_key=anchor_from_ref(item_ref),
                        text_content=cleaned_picture_text,
                        caption=caption,
                        image_mime=image_mime,
                        image_data=image_data,
                    )
                )
                continue

            if label == "table":
                caption = caption_from_item(item, doc)
                table_text = table_text_from_item(item, doc)
                units.append(
                    ParsedUnit(
                        unit_type="table",
                        page_number=page_number,
                        section_name=current_section,
                        anchor_key=anchor_from_ref(item_ref),
                        text_content=table_text,
                        caption=caption,
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
            raise RuntimeError("caption_text() did not return a string.")
        except Exception as exc:
            raise RuntimeError("Failed to extract item caption.") from exc
    return ""


def markdown_from_item(item: Any, doc: Any) -> str:
    export_to_markdown = getattr(item, "export_to_markdown", None)
    if not callable(export_to_markdown):
        raise RuntimeError("Item does not expose export_to_markdown().")
    try:
        value = export_to_markdown(doc)
    except Exception as exc:
        raise RuntimeError("Failed to export item markdown.") from exc
    if not isinstance(value, str):
        raise RuntimeError("export_to_markdown() did not return text.")
    return value.strip()


def table_text_from_item(item: Any, doc: Any) -> str:
    export_to_dataframe = getattr(item, "export_to_dataframe", None)
    if not callable(export_to_dataframe):
        raise RuntimeError("Table item does not expose export_to_dataframe().")
    try:
        dataframe = export_to_dataframe(doc)
    except Exception as exc:
        raise RuntimeError("Failed to export table dataframe.") from exc
    to_markdown = getattr(dataframe, "to_markdown", None)
    if not callable(to_markdown):
        raise RuntimeError("Table dataframe does not expose to_markdown().")
    try:
        value = to_markdown(index=False)
    except Exception as exc:
        raise RuntimeError("Failed to render table markdown.") from exc
    if not isinstance(value, str):
        raise RuntimeError("Table markdown renderer did not return text.")
    return value.strip()


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


def build_units(parsed_units: list[ParsedUnit]) -> list[dict[str, object]]:
    settings = get_settings()
    units: list[dict[str, object]] = []
    for unit in parsed_units:
        canonical_text = compose_text_content(
            unit_type=unit.unit_type,
            text_content=unit.text_content,
            caption=unit.caption,
        )
        terms = term_frequencies(canonical_text)
        units.append(
            {
                "unit_type": unit.unit_type,
                "page_number": unit.page_number,
                "section_name": unit.section_name,
                "anchor_key": unit.anchor_key,
                "text_content": canonical_text,
                "caption": unit.caption,
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
