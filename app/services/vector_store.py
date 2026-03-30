from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import get_settings


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    device = os.getenv("SEARCHY_VECTOR_DEVICE")
    if device:
        return SentenceTransformer(settings.vector_model_name, device=device)
    return SentenceTransformer(settings.vector_model_name)


def faiss_path_for_db(db_path: Path) -> Path:
    return db_path.with_suffix(".faiss")


def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_embedding_model()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype=np.float32)


def rebuild_faiss_index(db_path: Path, rows: list[tuple[int, str]]) -> None:
    index_path = faiss_path_for_db(db_path)
    if not rows:
        if index_path.exists():
            index_path.unlink()
        return

    content_unit_ids = np.asarray([row[0] for row in rows], dtype=np.int64)
    texts = [row[1] for row in rows]
    vectors = embed_texts(texts)
    dimension = int(vectors.shape[1])
    base_index = faiss.IndexFlatIP(dimension)
    index = faiss.IndexIDMap(base_index)
    index.add_with_ids(vectors, content_unit_ids)
    faiss.write_index(index, str(index_path))


def query_faiss_index(db_path: Path, query: str, limit: int = 100) -> list[tuple[int, float]]:
    index_path = faiss_path_for_db(db_path)
    if not index_path.exists():
        return []
    index = faiss.read_index(str(index_path))
    query_vector = embed_texts([query])
    scores, ids = index.search(query_vector, limit)
    results: list[tuple[int, float]] = []
    for content_unit_id, score in zip(ids[0], scores[0], strict=True):
        if int(content_unit_id) == -1:
            continue
        results.append((int(content_unit_id), float(score)))
    return results
