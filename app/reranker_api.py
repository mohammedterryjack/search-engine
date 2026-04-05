from __future__ import annotations

import os
from functools import lru_cache

import torch

from fastapi import FastAPI, Header, HTTPException, Request
from sentence_transformers import CrossEncoder


app = FastAPI(title="SearChi Reranker")

MODEL_NAME = os.getenv("SEARCHY_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L4-v2")
DEVICE = os.getenv("SEARCHY_RERANKER_DEVICE")
MAX_LENGTH = int(os.getenv("SEARCHY_RERANKER_MAX_LENGTH", "512"))
BATCH_SIZE = int(os.getenv("SEARCHY_RERANKER_BATCH_SIZE", "16"))
STATUS_TOKEN = os.getenv("SEARCHY_STATUS_TOKEN", "searchi-local-status")


@lru_cache(maxsize=1)
def get_model() -> CrossEncoder:
    kwargs: dict[str, object] = {
        "max_length": MAX_LENGTH,
        "model_kwargs": {"torch_dtype": torch.float32},
    }
    if DEVICE:
        kwargs["device"] = DEVICE
    return CrossEncoder(MODEL_NAME, **kwargs)


@app.on_event("startup")
def warm_model() -> None:
    get_model()


@app.get("/internal/health")
async def health(x_searchi_status_token: str | None = Header(default=None)) -> dict[str, object]:
    if x_searchi_status_token != STATUS_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")
    model = get_model()
    return {
        "status": "ok",
        "model_name": MODEL_NAME,
        "device": getattr(model.model, "device", "unknown").type if hasattr(model, "model") else "unknown",
        "max_length": MAX_LENGTH,
        "batch_size": BATCH_SIZE,
    }


@app.post("/rerank")
async def rerank(request: Request) -> list[dict[str, float | int]]:
    payload = await request.json()
    query = str(payload.get("query", ""))
    results = list(payload.get("results", []))
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    if not results:
        return []

    model = get_model()
    pairs = [(query, str(item.get("text_content", ""))) for item in results]
    scores = model.predict(pairs, batch_size=BATCH_SIZE, show_progress_bar=False)

    reranked = []
    for item, score in zip(results, scores, strict=True):
        reranked.append(
            {
                "content_unit_id": int(item["content_unit_id"]),
                "score": float(score),
            }
        )
    reranked.sort(key=lambda item: item["score"], reverse=True)
    return reranked
