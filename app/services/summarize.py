from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import get_settings


def summarize_single_result_stream(text: str):
    settings = get_settings()
    if not settings.enable_summarizer or not text:
        return

    # Truncate text to reasonable length for summarization
    max_chars = 2000
    truncated_text = text[:max_chars]

    payload = {
        "text": truncated_text,
        "max_length": 150,  # ~2-3 sentences
        "min_length": 20,
    }

    try:
        request = urllib.request.Request(
            f"{settings.summarizer_url}/summarize",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=settings.summarizer_timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            summary = result.get("summary", "")
            if summary:
                # Return summary all at once (no streaming from HF pipeline by default)
                yield summary
    except Exception as exc:
        print(f"Summarizer error: {exc}")
        return
