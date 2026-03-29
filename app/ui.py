from __future__ import annotations

import html
import re


def highlight_terms(text: str, query: str) -> str:
    escaped = html.escape(text)
    tokens = sorted({token for token in query.split() if token.strip()}, key=len, reverse=True)
    for token in tokens:
        pattern = re.compile(re.escape(html.escape(token)), re.IGNORECASE)
        escaped = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", escaped)
    return escaped


def truncate_text(text: str, limit: int = 320) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
