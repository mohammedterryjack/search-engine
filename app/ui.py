from __future__ import annotations

import html
import re

from app.services.tokenize import normalize_token, normalized_terms


WORD_RE = re.compile(r"[A-Za-z0-9]+")


def highlight_terms(text: str, query: str) -> str:
    matched_terms = set(normalized_terms(query))
    if not matched_terms:
        return html.escape(text)

    result_parts: list[str] = []
    last_index = 0
    for match in WORD_RE.finditer(text):
        start, end = match.span()
        result_parts.append(html.escape(text[last_index:start]))
        surface = match.group(0)
        normalized = normalize_token(surface)
        escaped_surface = html.escape(surface)
        if normalized in matched_terms:
            result_parts.append(f"<mark>{escaped_surface}</mark>")
        else:
            result_parts.append(escaped_surface)
        last_index = end
    result_parts.append(html.escape(text[last_index:]))
    return "".join(result_parts)


def truncate_text(text: str, limit: int = 320) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
