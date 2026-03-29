from __future__ import annotations

import json
import math
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from app.config import get_settings
from app.db.global_store import GlobalStore
from app.db.source_store import SourceStore
from app.models import SearchResult
from app.services.tokenize import normalized_terms


def bm25_score(
    query_terms: list[str],
    doc_term_freqs: dict[str, int],
    doc_length: int,
    avg_doc_length: float,
    term_doc_counts: dict[str, int],
    total_docs: int,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    score = 0.0
    for term in query_terms:
        freq = doc_term_freqs.get(term, 0)
        if freq == 0:
            continue
        doc_count = term_doc_counts.get(term, 0)
        idf = math.log(1 + (total_docs - doc_count + 0.5) / (doc_count + 0.5))
        denom = freq + k1 * (1 - b + b * (doc_length / max(avg_doc_length, 1)))
        score += idf * ((freq * (k1 + 1)) / max(denom, 1e-6))
    return score


def search_all_sources(query: str, source_root_ids: set[int] | None = None) -> list[SearchResult]:
    terms = normalized_terms(query)
    if not terms:
        return []

    global_store = GlobalStore()
    source_roots = global_store.list_source_roots()
    if source_root_ids:
        source_roots = [row for row in source_roots if int(row["id"]) in source_root_ids]

    results: list[SearchResult] = []
    for source_root in source_roots:
        source_results = search_source_db(
            source_root_id=int(source_root["id"]),
            source_path=str(source_root["source_path"]),
            db_path=Path(str(source_root["db_path"])),
            terms=terms,
        )
        results.extend(source_results)

    if not results:
        return []

    reranked = rerank_results(query, results[:100])
    return reranked


def search_source_db(
    *,
    source_root_id: int,
    source_path: str,
    db_path: Path,
    terms: list[str],
) -> list[SearchResult]:
    if not db_path.exists():
        return []

    store = SourceStore(db_path)
    with store.connect() as conn:
        placeholders = ", ".join("?" for _ in terms)
        rows = conn.execute(
            f"""
            SELECT
                cu.id AS content_unit_id,
                cu.document_id,
                cu.unit_type,
                cu.page_number,
                cu.section_name,
                cu.display_text,
                cu.token_count,
                d.source_path AS document_path,
                d.filename,
                tp.term,
                tp.term_frequency
            FROM term_postings tp
            JOIN content_units cu ON cu.id = tp.content_unit_id
            JOIN documents d ON d.id = cu.document_id
            WHERE tp.term IN ({placeholders})
            """,
            terms,
        ).fetchall()
        if not rows:
            return []

        term_doc_counts = _term_doc_counts(conn, terms)
        total_docs = _total_content_units(conn)
        avg_doc_length = _average_doc_length(conn)

    grouped: dict[int, dict[str, object]] = {}
    for row in rows:
        entry = grouped.setdefault(
            int(row["content_unit_id"]),
            {
                "document_id": int(row["document_id"]),
                "unit_type": str(row["unit_type"]),
                "page_number": row["page_number"],
                "section_name": str(row["section_name"]),
                "display_text": str(row["display_text"]),
                "document_path": str(row["document_path"]),
                "filename": str(row["filename"]),
                "token_count": int(row["token_count"]),
                "term_freqs": {},
            },
        )
        entry["term_freqs"][str(row["term"])] = int(row["term_frequency"])

    scored: list[SearchResult] = []
    for content_unit_id, entry in grouped.items():
        score = bm25_score(
            query_terms=terms,
            doc_term_freqs=entry["term_freqs"],
            doc_length=int(entry["token_count"]),
            avg_doc_length=avg_doc_length,
            term_doc_counts=term_doc_counts,
            total_docs=total_docs,
        )
        scored.append(
            SearchResult(
                source_root_id=source_root_id,
                source_path=source_path,
                document_id=int(entry["document_id"]),
                content_unit_id=content_unit_id,
                document_path=str(entry["document_path"]),
                filename=str(entry["filename"]),
                unit_type=str(entry["unit_type"]),
                page_number=int(entry["page_number"]) if entry["page_number"] is not None else None,
                section_name=str(entry["section_name"]),
                display_text=str(entry["display_text"]),
                score=score,
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:100]


def _term_doc_counts(conn: sqlite3.Connection, terms: list[str]) -> dict[str, int]:
    placeholders = ", ".join("?" for _ in terms)
    rows = conn.execute(
        f"""
        SELECT term, COUNT(*) AS doc_count
        FROM term_postings
        WHERE term IN ({placeholders})
        GROUP BY term
        """,
        terms,
    ).fetchall()
    return {str(row["term"]): int(row["doc_count"]) for row in rows}


def _total_content_units(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS total FROM content_units").fetchone()
    return int(row["total"]) if row is not None else 0


def _average_doc_length(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT AVG(token_count) AS avg_tokens FROM content_units").fetchone()
    value = row["avg_tokens"] if row is not None else 0
    return float(value or 0.0)


def rerank_results(query: str, results: list[SearchResult]) -> list[SearchResult]:
    settings = get_settings()
    if not settings.enable_reranker or not results:
        return results

    payload = {
        "query": query,
        "results": [
            {
                "content_unit_id": result.content_unit_id,
                "display_text": result.display_text,
                "score": result.score,
            }
            for result in results
        ],
    }
    try:
        request = urllib.request.Request(
            f"{settings.reranker_url}/rerank",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read().decode("utf-8")
        scores = json.loads(body)
        by_id = {int(item["content_unit_id"]): float(item["score"]) for item in scores}
        for result in results:
            result.score = by_id.get(result.content_unit_id, result.score)
        results.sort(key=lambda item: item.score, reverse=True)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        results.sort(key=lambda item: item.score, reverse=True)
    return results
