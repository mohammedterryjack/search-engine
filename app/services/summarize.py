from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from app.models import SearchResult


def summarize_results_stream(query: str, results: list[SearchResult], top_n: int):
    settings = get_settings()
    if not settings.enable_summarizer or not results:
        return

    relevant_results = results[:top_n]
    context_parts = []
    for i, res in enumerate(relevant_results, start=1):
        text = (res.display_text or "").strip()
        if text:
            context_parts.append(f"[{i}] {text}")
    
    if not context_parts:
        return

    context_str = "\n".join(context_parts)
    prompt = f"""Using the search results provided below, write a single, natural-sounding paragraph that synthesizes the information to answer the query: '{query}'. 

Follow these strict rules:
1. Provide a cohesive summary, NOT a list of quotes.
2. Use inline citations in the format [N] immediately following the information sourced from result N.
3. Keep the entire response to exactly one paragraph.
4. Respond ONLY with the summary.

SEARCH RESULTS:
{context_str}"""

    payload = {
        "model": settings.summarizer_model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.1
        }
    }

    try:
        request = urllib.request.Request(
            f"{settings.summarizer_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=settings.summarizer_timeout) as response:
            for line in response:
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    text = chunk.get("response", "")
                    if text:
                        yield text
                    if chunk.get("done"):
                        break
    except Exception as exc:
        print(f"Summarizer streaming error: {exc}")
        return
