from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import get_settings


class VectorStoreError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    device = os.getenv("SEARCHY_VECTOR_DEVICE")
    try:
        if device:
            return SentenceTransformer(settings.vector_model_name, device=device)
        return SentenceTransformer(settings.vector_model_name)
    except Exception as exc:
        raise VectorStoreError(
            f"Failed to load embedding model '{settings.vector_model_name}'."
        ) from exc


def faiss_path_for_db(db_path: Path) -> Path:
    return db_path.with_suffix(".faiss")


def embed_texts(texts: list[str]) -> np.ndarray:
    try:
        model = get_embedding_model()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
    except VectorStoreError:
        raise
    except Exception as exc:
        raise VectorStoreError("Failed to embed text for semantic search.") from exc


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


def update_faiss_index(
    db_path: Path,
    *,
    remove_ids: list[int] | None = None,
    add_rows: list[tuple[int, str]] | None = None,
) -> None:
    remove_ids = remove_ids or []
    add_rows = add_rows or []
    index_path = faiss_path_for_db(db_path)

    if not index_path.exists():
        if add_rows:
            rebuild_faiss_index(db_path, add_rows)
        return

    index = faiss.read_index(str(index_path))
    if remove_ids:
        ids = np.asarray(remove_ids, dtype=np.int64)
        index.remove_ids(ids)

    if add_rows:
        content_unit_ids = np.asarray([row[0] for row in add_rows], dtype=np.int64)
        texts = [row[1] for row in add_rows]
        vectors = embed_texts(texts)
        index.add_with_ids(vectors, content_unit_ids)

    ntotal = getattr(index, "ntotal", 0)
    if ntotal == 0:
        index_path.unlink(missing_ok=True)
        return
    faiss.write_index(index, str(index_path))


def faiss_index_ids(db_path: Path) -> set[int]:
    index_path = faiss_path_for_db(db_path)
    if not index_path.exists():
        return set()
    index = faiss.read_index(str(index_path))
    id_map = getattr(index, "id_map", None)
    if id_map is None:
        return set()
    ids = faiss.vector_to_array(id_map)
    return {int(value) for value in ids.tolist()}


def faiss_reconciliation_report(db_path: Path, expected_rows: list[tuple[int, str]]) -> dict[str, object]:
    expected_ids = {int(content_unit_id) for content_unit_id, _text in expected_rows}
    actual_ids = faiss_index_ids(db_path)
    missing_in_faiss = sorted(expected_ids - actual_ids)
    stale_in_faiss = sorted(actual_ids - expected_ids)
    return {
        "expected_count": len(expected_ids),
        "actual_count": len(actual_ids),
        "missing_in_faiss": missing_in_faiss,
        "stale_in_faiss": stale_in_faiss,
        "status": "ok" if not missing_in_faiss and not stale_in_faiss else "mismatch",
    }


def query_faiss_index(db_path: Path, query: str, limit: int = 100) -> list[tuple[int, float]]:
    try:
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
    except VectorStoreError:
        raise
    except Exception as exc:
        raise VectorStoreError("Failed to query the semantic index.") from exc
