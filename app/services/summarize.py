from __future__ import annotations

import codecs
import json
import urllib.error
import urllib.request

from app.config import get_settings


def _stream_passthrough_response(response):
    decoder = codecs.getincrementaldecoder("utf-8")()
    read_chunk = getattr(response, "read1", None)
    while True:
        if callable(read_chunk):
            chunk = read_chunk(1)
        else:
            chunk = response.read(1)
        if not chunk:
            break
        text = decoder.decode(chunk)
        if text:
            yield text

    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


def summarize_single_result_stream(
    text: str,
    image_data: str | None = None,
    image_mime: str | None = None,
):
    settings = get_settings()
    if not settings.enable_summarizer or (not text and not image_data):
        return

    payload = {
        "text": text,
        "image_data": image_data,
        "image_mime": image_mime,
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
            yield from _stream_passthrough_response(response)
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
            yield from _stream_passthrough_response(response)
    except Exception as exc:
        print(f"Answer generation error: {exc}")
        return
