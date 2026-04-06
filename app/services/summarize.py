from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from app.config import get_settings


WORD_WITH_TRAILING_SPACE_RE = re.compile(r"\S+\s*")


def _stream_words_from_response(response):
    buffer = ""
    while True:
        chunk = response.read(32)
        if not chunk:
            break
        buffer += chunk.decode("utf-8")

        matches = list(WORD_WITH_TRAILING_SPACE_RE.finditer(buffer))
        if not matches:
            continue

        last_consumed = 0
        for match in matches:
            # Keep the final partial token in the buffer until more text arrives.
            if match.end() == len(buffer) and not buffer[-1].isspace():
                break
            yield match.group(0)
            last_consumed = match.end()

        if last_consumed:
            buffer = buffer[last_consumed:]

    if buffer:
        yield buffer


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
            yield from _stream_words_from_response(response)
    except Exception as exc:
        print(f"Summarizer error: {exc}")
        return


def answer_search_results_stream(question: str, sources: list[dict[str, object]]):
    settings = get_settings()
    if not settings.enable_summarizer or not question or not sources:
        return

    payload = {
        "question": question,
        "sources": sources,
        "stream": True,
    }

    try:
        request = urllib.request.Request(
            f"{settings.summarizer_url}/answer",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=settings.summarizer_timeout) as response:
            yield from _stream_words_from_response(response)
    except Exception as exc:
        print(f"Answer generation error: {exc}")
        return
