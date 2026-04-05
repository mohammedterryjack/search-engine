from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import get_settings


def summarize_single_result_stream(text: str):
    settings = get_settings()
    if not settings.enable_summarizer or not text:
        return

    payload = {
        "text": text,
        "max_length": 150,  # ~2-3 sentences
        "min_length": 20,
        "stream": True,
    }

    try:
        request = urllib.request.Request(
            f"{settings.summarizer_url}/summarize",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=settings.summarizer_timeout) as response:
            # Stream chunks as they arrive
            while True:
                chunk = response.read(64)  # Read in small chunks
                if not chunk:
                    break
                yield chunk.decode("utf-8")
    except Exception as exc:
        print(f"Summarizer error: {exc}")
        return
