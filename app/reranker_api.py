from __future__ import annotations

from collections import Counter

from fastapi import FastAPI, Request


app = FastAPI(title="SirChi Reranker")


def overlap_score(query: str, text: str, base_score: float) -> float:
    query_terms = Counter(query.lower().split())
    text_tokens = text.lower().split()
    overlap = sum(query_terms[token] for token in text_tokens if token in query_terms)
    return base_score + overlap * 0.15


@app.post("/rerank")
async def rerank(request: Request) -> list[dict[str, float | int]]:
    payload = await request.json()
    query = str(payload.get("query", ""))
    results = list(payload.get("results", []))
    reranked = []
    for item in results:
        reranked.append(
            {
                "content_unit_id": int(item["content_unit_id"]),
                "score": overlap_score(query, str(item["display_text"]), float(item["score"])),
            }
        )
    reranked.sort(key=lambda item: item["score"], reverse=True)
    return reranked
