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
from app.models import SearchResponse, SearchResult
from app.services.tokenize import normalized_terms
from app.services.vector_store import query_faiss_index


class SearchPipelineError(RuntimeError):
    """Raised when an enabled search stage fails."""


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


def search_all_sources(
    query: str,
    source_root_ids: set[int] | None = None,
    *,
    unit_types: set[str] | None = None,
    vector_min_score: float | None = None,
) -> SearchResponse:
    terms = normalized_terms(query)
    if not terms:
        return SearchResponse(results=[])

    global_store = GlobalStore()
    source_roots = global_store.list_source_roots()
    if source_root_ids:
        source_roots = [row for row in source_roots if int(row["id"]) in source_root_ids]

    results: list[SearchResult] = []
    warnings: list[str] = []
    for source_root in source_roots:
        source_results, source_warning = search_source_db(
            source_root_id=int(source_root["id"]),
            source_path=str(source_root["source_path"]),
            db_path=Path(str(source_root["db_path"])),
            query=query,
            terms=terms,
            unit_types=unit_types,
            vector_min_score=vector_min_score,
        )
        results.extend(source_results)
        if source_warning:
            warnings.append(source_warning)

    if not results:
        return SearchResponse(results=[], warning=" ".join(warnings) if warnings else None)

    reranked, rerank_warning = rerank_results(query, results[:100])
    if unit_types:
        reranked = [result for result in reranked if result.unit_type in unit_types]
    if rerank_warning:
        warnings.append(rerank_warning)
    return SearchResponse(results=reranked, warning=" ".join(warnings) if warnings else None)


def search_source_db(
    *,
    source_root_id: int,
    source_path: str,
    db_path: Path,
    query: str,
    terms: list[str],
    unit_types: set[str] | None = None,
    vector_min_score: float | None = None,
) -> tuple[list[SearchResult], str | None]:
    if not db_path.exists():
        return [], None

    lexical_results = lexical_search_source_db(
        source_root_id=source_root_id,
        source_path=source_path,
        db_path=db_path,
        terms=terms,
        unit_types=unit_types,
    )
    semantic_results: list[SearchResult] = []
    warning: str | None = None
    settings = get_settings()
    if settings.enable_vector_retrieval:
        semantic_results, warning = semantic_search_source_db(
            source_root_id=source_root_id,
            source_path=source_path,
            db_path=db_path,
            query=query,
            unit_types=unit_types,
            vector_min_score=vector_min_score,
        )
    return fuse_results(lexical_results, semantic_results, limit=100), warning


def lexical_search_source_db(
    *,
    source_root_id: int,
    source_path: str,
    db_path: Path,
    terms: list[str],
    unit_types: set[str] | None = None,
) -> list[SearchResult]:
    store = SourceStore(db_path)
    with store.connect() as conn:
        term_placeholders = ", ".join("?" for _ in terms)
        params: list[object] = list(terms)
        unit_type_clause = ""
        if unit_types:
            unit_placeholders = ", ".join("?" for _ in unit_types)
            unit_type_clause = f" AND cu.unit_type IN ({unit_placeholders})"
            params.extend(sorted(unit_types))
        rows = conn.execute(
            f"""
            SELECT
                cu.id AS content_unit_id,
                cu.document_id,
                cu.unit_type,
                cu.page_number,
                cu.section_name,
                cu.display_text,
                cu.image_mime,
                cu.image_data,
                cu.token_count,
                d.source_path AS document_path,
                d.filename,
                tp.term,
                tp.term_frequency
            FROM term_postings tp
            JOIN content_units cu ON cu.id = tp.content_unit_id
            JOIN documents d ON d.id = cu.document_id
            WHERE tp.term IN ({term_placeholders}){unit_type_clause}
            """,
            params,
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
                "image_mime": row["image_mime"],
                "image_data": row["image_data"],
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
                image_mime=entry["image_mime"],
                image_data=entry["image_data"],
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:100]


def semantic_search_source_db(
    *,
    source_root_id: int,
    source_path: str,
    db_path: Path,
    query: str,
    unit_types: set[str] | None = None,
    vector_min_score: float | None = None,
) -> tuple[list[SearchResult], str | None]:
    store = SourceStore(db_path)
    vector_hits = query_faiss_index(db_path, query, limit=300)
    if not vector_hits:
        return [], None
    effective_min_score = vector_min_score if vector_min_score is not None else float("-inf")
    content_unit_ids = [content_unit_id for content_unit_id, _score in vector_hits]
    rows = store.content_units_by_ids(content_unit_ids)
    row_by_id = {int(row["content_unit_id"]): row for row in rows}
    results: list[SearchResult] = []
    stale_ids: list[int] = []
    for content_unit_id, score in vector_hits:
        row = row_by_id.get(content_unit_id)
        if row is None:
            stale_ids.append(content_unit_id)
            continue
        if unit_types and str(row["unit_type"]) not in unit_types:
            continue
        if score < effective_min_score:
            continue
        results.append(
            SearchResult(
                source_root_id=source_root_id,
                source_path=source_path,
                document_id=int(row["document_id"]),
                content_unit_id=content_unit_id,
                document_path=str(row["document_path"]),
                filename=str(row["filename"]),
                unit_type=str(row["unit_type"]),
                page_number=int(row["page_number"]) if row["page_number"] is not None else None,
                section_name=str(row["section_name"]),
                display_text=str(row["display_text"]),
                score=float(score),
                image_mime=row["image_mime"],
                image_data=row["image_data"],
            )
        )
    warning = None
    if stale_ids:
        from app.services.vector_store import update_faiss_index

        update_faiss_index(db_path, remove_ids=stale_ids)
        warning = f"Removed {len(stale_ids)} stale vector entr{'y' if len(stale_ids) == 1 else 'ies'} from the semantic index."
    return results[:100], warning


def fuse_results(
    lexical_results: list[SearchResult],
    semantic_results: list[SearchResult],
    *,
    limit: int,
) -> list[SearchResult]:
    if not lexical_results and not semantic_results:
        return []

    by_id: dict[int, SearchResult] = {}
    fused_scores: dict[int, float] = {}
    lexical_rank = {result.content_unit_id: rank for rank, result in enumerate(lexical_results, start=1)}
    semantic_rank = {result.content_unit_id: rank for rank, result in enumerate(semantic_results, start=1)}

    for result in lexical_results + semantic_results:
        by_id[result.content_unit_id] = result

    for content_unit_id in by_id:
        score = 0.0
        if content_unit_id in lexical_rank:
            score += 1.0 / (60 + lexical_rank[content_unit_id])
        if content_unit_id in semantic_rank:
            score += 1.0 / (60 + semantic_rank[content_unit_id])
        fused_scores[content_unit_id] = score

    fused = list(by_id.values())
    for result in fused:
        result.score = fused_scores[result.content_unit_id]
    fused.sort(key=lambda item: item.score, reverse=True)
    return fused[:limit]


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


def rerank_results(query: str, results: list[SearchResult]) -> tuple[list[SearchResult], str | None]:
    settings = get_settings()
    if not settings.enable_reranker or not results:
        return results, None

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
            if result.content_unit_id not in by_id:
                raise SearchPipelineError(
                    f"Reranker response did not include content_unit_id={result.content_unit_id}."
                )
            result.score = by_id[result.content_unit_id]
        results.sort(key=lambda item: item.score, reverse=True)
        return results, None
    except urllib.error.HTTPError as exc:
        raise SearchPipelineError(
            f"Reranker returned HTTP {exc.code} from {settings.reranker_url}."
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return results, "Reranker request timed out. Showing lexical/vector ranking without reranking."
        raise SearchPipelineError(
            f"Could not reach reranker at {settings.reranker_url}: {exc.reason}."
        ) from exc
    except TimeoutError as exc:
        return results, "Reranker request timed out. Showing lexical/vector ranking without reranking."
    except json.JSONDecodeError as exc:
        raise SearchPipelineError("Reranker returned invalid JSON.") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise SearchPipelineError(f"Invalid reranker response: {exc}.") from exc
