from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
SUMMARY_MODEL = os.getenv("SEARCHY_SUMMARY_MODEL", "qwen2.5:0.5b-instruct")
AI_MODEL = os.getenv("SEARCHY_AI_MODEL", "qwen3.5:0.8b")
OLLAMA_TIMEOUT = float(os.getenv("SEARCHY_SUMMARIZER_TIMEOUT", "180.0"))
OLLAMA_NUM_CTX = int(os.getenv("SEARCHY_SUMMARIZER_NUM_CTX", "32768"))


def _build_messages(text: str, min_length: int, max_length: int) -> list[dict[str, str]]:
    trimmed = text.strip()
    system_prompt = (
        "You are a careful summarization assistant. "
        "Summarize the provided text faithfully and concisely. "
        "Keep only the main claims, findings, and conclusions. "
        "Do not add information that is not present in the source. "
        "Do not use bullet points. "
        f"Write 2 to 3 sentences, aiming for roughly {min_length} to {max_length} words. "
        "If the text is too short to summarize, return a one-sentence restatement."
    )
    user_prompt = f"Summarize the following text.\n\n<text>\n{trimmed}\n</text>"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _ollama_request(path: str, payload: dict[str, object] | None = None) -> urllib.request.Request:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    return urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=data,
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def _ollama_tags() -> dict[str, object]:
    request = _ollama_request("/api/tags")
    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _model_available() -> bool:
    data = _ollama_tags()
    models = data.get("models", [])
    available = {str(model.get("name", "")) for model in models if isinstance(model, dict)}
    return SUMMARY_MODEL in available and AI_MODEL in available


def _warm_model(model_name: str) -> None:
    request = _ollama_request(
        "/api/chat",
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "options": {"num_predict": 8, "temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
        },
    )
    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(str(data["error"]))


def _stream_generate(payload: dict[str, object]):
    request = _ollama_request("/api/chat", payload)
    # Avoid socket read timeouts during streamed generation; some models take a
    # while before yielding the first chunk, especially on cold starts.
    with urllib.request.urlopen(request) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError(str(data["error"]))
            message = data.get("message", {})
            text = str(message.get("content", "")) if isinstance(message, dict) else ""
            if text:
                yield text
            if data.get("done"):
                return


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Checking Ollama summary model %s and AI model %s at %s",
        SUMMARY_MODEL,
        AI_MODEL,
        OLLAMA_URL,
    )
    if not _model_available():
        raise RuntimeError(
            f"Ollama models {SUMMARY_MODEL} and/or {AI_MODEL} are not available"
        )
    _warm_model(SUMMARY_MODEL)
    _warm_model(AI_MODEL)
    yield


app = FastAPI(lifespan=lifespan)


class SummarizeRequest(BaseModel):
    text: str
    image_data: str | None = None
    image_mime: str | None = None
    max_length: int = 150
    min_length: int = 20
    stream: bool = False


class AnswerSource(BaseModel):
    id: int
    citation: str
    text: str
    image_data: str | None = None
    image_mime: str | None = None


class AnswerRequest(BaseModel):
    question: str
    sources: list[AnswerSource]
    stream: bool = False


def _build_answer_messages(question: str, sources: list[AnswerSource]) -> list[dict[str, object]]:
    system_prompt = (
        "You are a careful research assistant. "
        "Answer the user's question using only the provided sources. "
        "Be concise, direct, and factual. "
        "Cite every substantive claim with source ids in square brackets, like [1] or [2]. "
        "If a sentence relies on more than one source, cite all relevant ids. "
        "If the sources do not contain enough information to answer fully, say so explicitly. "
        "Do not use bullet points unless the user asks for them. "
        "Do not invent facts, quotes, or citations. "
        "Return only the answer text."
    )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": system_prompt},
    ]
    messages.append(
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question.strip()}\n\n"
                "I will now provide the numbered sources you must rely on."
            ),
        }
    )
    for source in sources:
        source_message: dict[str, object] = {
            "role": "user",
            "content": (
                f"<source id=\"{source.id}\" citation=\"{source.citation}\">\n"
                f"{source.text.strip()}\n"
                "</source>\n"
                "If an image is attached to this message, treat it as part of the same source."
            ),
        }
        if source.image_data:
            source_message["images"] = [source.image_data]
        messages.append(source_message)
    messages.append(
        {
            "role": "user",
            "content": (
                "Answer the question using only the numbered sources already provided. "
                "Write a concise answer with inline citations."
            ),
        }
    )
    return messages


@app.post("/summarize")
async def summarize(request: SummarizeRequest):
    try:
        messages = _build_messages(request.text, request.min_length, request.max_length)
        if request.image_data and len(messages) > 1:
            user_message = dict(messages[1])
            user_message["content"] = (
                f"{user_message['content']}\n\n"
                "If an image is attached, use it as additional context for the summary."
            )
            user_message["images"] = [request.image_data]
            messages[1] = user_message
        payload = {
            "model": SUMMARY_MODEL,
            "messages": messages,
            "stream": request.stream,
            "options": {
                "temperature": 0.2,
                "num_predict": max(request.max_length * 2, 64),
                "num_ctx": OLLAMA_NUM_CTX,
            },
        }

        if request.stream:
            return StreamingResponse(_stream_generate(payload), media_type="text/plain")

        upstream_request = _ollama_request("/api/chat", payload)
        with urllib.request.urlopen(upstream_request, timeout=OLLAMA_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        message = data.get("message", {})
        summary = str(message.get("content", "")).strip() if isinstance(message, dict) else ""
        return {"summary": summary}
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return {"summary": "Summarization failed", "error": str(e)}


@app.post("/answer")
async def answer(request: AnswerRequest):
    try:
        messages = _build_answer_messages(request.question, request.sources)
        payload = {
            "model": AI_MODEL,
            "messages": messages,
            "stream": request.stream,
            "options": {
                "temperature": 0.1,
                "num_predict": 512,
                "num_ctx": OLLAMA_NUM_CTX,
            },
        }

        if request.stream:
            return StreamingResponse(_stream_generate(payload), media_type="text/plain")

        upstream_request = _ollama_request("/api/chat", payload)
        with urllib.request.urlopen(upstream_request, timeout=OLLAMA_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        message = data.get("message", {})
        answer_text = str(message.get("content", "")).strip() if isinstance(message, dict) else ""
        return {"answer": answer_text}
    except Exception as e:
        logger.error(f"Answer generation failed: {e}")
        return {"answer": "Answer generation failed", "error": str(e)}


@app.get("/health")
async def health():
    try:
        if _model_available():
            return {
                "status": "healthy",
                "model": f"summary={SUMMARY_MODEL}; answer={AI_MODEL}",
                "summary_model": SUMMARY_MODEL,
                "answer_model": AI_MODEL,
            }
        return {
            "status": "model-missing",
            "model": f"summary={SUMMARY_MODEL}; answer={AI_MODEL}",
            "summary_model": SUMMARY_MODEL,
            "answer_model": AI_MODEL,
        }
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {
            "status": "error",
            "model": f"summary={SUMMARY_MODEL}; answer={AI_MODEL}",
            "summary_model": SUMMARY_MODEL,
            "answer_model": AI_MODEL,
            "error": str(exc),
        }
