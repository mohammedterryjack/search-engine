from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS


def load_document(path: Path) -> tuple[str, str]:
    raw_bytes = path.read_bytes()
    content_hash = hashlib.sha1(raw_bytes).hexdigest()
    suffix = path.suffix.casefold()

    if suffix in TEXT_EXTENSIONS:
        return _normalize_text(raw_bytes.decode("utf-8", errors="ignore")), content_hash

    if suffix in PDF_EXTENSIONS:
        return _extract_pdf_text(raw_bytes), content_hash

    raise ValueError(f"Unsupported document type: {path.suffix}")


def _extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(raw_bytes))
    except Exception as exc:
        logger.warning("Failed to open PDF: %s", exc)
        return ""

    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            pages.append(_normalize_text(page.extract_text() or ""))
        except Exception as exc:
            logger.warning("Failed to extract PDF page %s: %s", index, exc)
            pages.append("")
    return "\f".join(pages)


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
