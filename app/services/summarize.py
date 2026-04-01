from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import get_settings


def summarize_single_result_stream(text: str):
    settings = get_settings()
    if not settings.enable_summarizer or not text:
        return

    prompt = f"Summarise the following text in plain english using 10 words or less.\n\nText: {text}\n\nSummary:"

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
