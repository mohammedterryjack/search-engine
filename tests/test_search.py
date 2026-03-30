from __future__ import annotations

import json
from pathlib import Path

from app.db.global_store import utc_now
from app.db.source_store import SourceStore
from app.models import SearchResult
from app.services.search import (
    bm25_score,
    fuse_results,
    lexical_search_source_db,
    rerank_results,
    semantic_search_source_db,
)
from app.services.tokenize import term_frequencies


def test_bm25_score_prefers_higher_term_frequency() -> None:
    high = bm25_score(
        query_terms=["chaos"],
        doc_term_freqs={"chaos": 3},
        doc_length=10,
        avg_doc_length=10.0,
        term_doc_counts={"chaos": 2},
        total_docs=20,
    )
    low = bm25_score(
        query_terms=["chaos"],
        doc_term_freqs={"chaos": 1},
        doc_length=10,
        avg_doc_length=10.0,
        term_doc_counts={"chaos": 2},
        total_docs=20,
    )
    assert high > low


def test_fuse_results_rewards_overlap() -> None:
    lexical = [
        SearchResult(1, "/src", 1, 10, "/doc1", "doc1", "section", 1, "A", "alpha", 1.0),
        SearchResult(1, "/src", 1, 20, "/doc2", "doc2", "section", 1, "B", "beta", 0.9),
    ]
    semantic = [
        SearchResult(1, "/src", 1, 10, "/doc1", "doc1", "section", 1, "A", "alpha", 0.8),
        SearchResult(1, "/src", 1, 30, "/doc3", "doc3", "section", 1, "C", "gamma", 0.7),
    ]

    fused = fuse_results(lexical, semantic, limit=10)
    assert fused[0].content_unit_id == 10


def test_semantic_search_respects_threshold(monkeypatch, tmp_path: Path) -> None:
    doc_path = tmp_path / "paper.pdf"
    doc_path.write_text("placeholder")
    store = SourceStore(tmp_path / "source.sqlite3")
    document_id = store.upsert_document(
        document_path=doc_path,
        status="indexed",
        page_count=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    store.replace_content_units(
        document_id,
        [
            {
                "unit_type": "section",
                "page_number": 1,
                "section_name": "Chaos",
                "anchor_key": "section-1",
                "text_content": "chaos attractor",
                "caption": "",
                "display_text": "chaos attractor",
                "token_count": 2,
                "created_at": utc_now(),
                "terms": term_frequencies("chaos attractor"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            }
        ],
    )

    monkeypatch.setattr(
        "app.services.search.query_faiss_index",
        lambda _db_path, _query, limit=300: [(1, 0.19)],
    )

    filtered, filtered_warning = semantic_search_source_db(
        source_root_id=1,
        source_path="/src",
        db_path=store.db_path,
        query="chaos system",
        vector_min_score=0.2,
    )
    assert filtered == []
    assert filtered_warning is None

    passed, passed_warning = semantic_search_source_db(
        source_root_id=1,
        source_path="/src",
        db_path=store.db_path,
        query="chaos system",
        vector_min_score=0.1,
    )
    assert passed_warning is None
    assert len(passed) == 1
    assert passed[0].content_unit_id == 1


def test_rerank_results_uses_reranker_response(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                [
                    {"content_unit_id": 2, "score": 0.9},
                    {"content_unit_id": 1, "score": 0.1},
                ]
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())

    results = [
        SearchResult(1, "/src", 1, 1, "/doc1", "doc1", "section", 1, "A", "alpha", 0.3),
        SearchResult(1, "/src", 1, 2, "/doc2", "doc2", "section", 1, "B", "beta", 0.2),
    ]
    reranked, warning = rerank_results("query", results)
    assert warning is None
    assert [item.content_unit_id for item in reranked] == [2, 1]


def test_rerank_results_timeout_falls_back_with_warning(monkeypatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))

    results = [
        SearchResult(1, "/src", 1, 1, "/doc1", "doc1", "section", 1, "A", "alpha", 0.3),
        SearchResult(1, "/src", 1, 2, "/doc2", "doc2", "section", 1, "B", "beta", 0.2),
    ]
    reranked, warning = rerank_results("query", results)
    assert [item.content_unit_id for item in reranked] == [1, 2]
    assert warning == "Reranker request timed out. Showing lexical/vector ranking without reranking."


def test_semantic_search_repairs_stale_vector_ids(monkeypatch, tmp_path: Path) -> None:
    doc_path = tmp_path / "paper.pdf"
    doc_path.write_text("placeholder")
    store = SourceStore(tmp_path / "source.sqlite3")
    document_id = store.upsert_document(
        document_path=doc_path,
        status="indexed",
        page_count=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    store.replace_content_units(
        document_id,
        [
            {
                "unit_type": "section",
                "page_number": 1,
                "section_name": "Chaos",
                "anchor_key": "section-1",
                "text_content": "chaos attractor",
                "caption": "",
                "display_text": "chaos attractor",
                "token_count": 2,
                "created_at": utc_now(),
                "terms": term_frequencies("chaos attractor"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            }
        ],
    )

    removed: list[int] = []
    monkeypatch.setattr(
        "app.services.search.query_faiss_index",
        lambda _db_path, _query, limit=300: [(999, 0.8), (1, 0.4)],
    )
    monkeypatch.setattr(
        "app.services.vector_store.update_faiss_index",
        lambda _db_path, remove_ids=None, add_rows=None: removed.extend(remove_ids or []),
    )

    results, warning = semantic_search_source_db(
        source_root_id=1,
        source_path="/src",
        db_path=store.db_path,
        query="chaos system",
        vector_min_score=0.1,
    )

    assert [item.content_unit_id for item in results] == [1]
    assert warning == "Removed 1 stale vector entry from the semantic index."
    assert removed == [999]


def test_lexical_search_respects_unit_type_filter(tmp_path: Path) -> None:
    doc_path = tmp_path / "paper.pdf"
    doc_path.write_text("placeholder")
    store = SourceStore(tmp_path / "source.sqlite3")
    document_id = store.upsert_document(
        document_path=doc_path,
        status="indexed",
        page_count=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    store.replace_content_units(
        document_id,
        [
            {
                "unit_type": "section",
                "page_number": 1,
                "section_name": "Section A",
                "anchor_key": "section-1",
                "text_content": "chaos attractor",
                "caption": "",
                "display_text": "chaos attractor",
                "token_count": 2,
                "created_at": utc_now(),
                "terms": term_frequencies("chaos attractor"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            },
            {
                "unit_type": "figure",
                "page_number": 1,
                "section_name": "Figure A",
                "anchor_key": "figure-1",
                "text_content": "chaos attractor",
                "caption": "Chaos figure",
                "display_text": "Chaos figure",
                "token_count": 2,
                "created_at": utc_now(),
                "terms": term_frequencies("chaos attractor"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            },
        ],
    )

    results = lexical_search_source_db(
        source_root_id=1,
        source_path="/src",
        db_path=store.db_path,
        terms=["chaos"],
        unit_types={"figure"},
    )

    assert len(results) == 1
    assert results[0].unit_type == "figure"


def test_semantic_search_respects_unit_type_filter(monkeypatch, tmp_path: Path) -> None:
    doc_path = tmp_path / "paper.pdf"
    doc_path.write_text("placeholder")
    store = SourceStore(tmp_path / "source.sqlite3")
    document_id = store.upsert_document(
        document_path=doc_path,
        status="indexed",
        page_count=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    store.replace_content_units(
        document_id,
        [
            {
                "unit_type": "section",
                "page_number": 1,
                "section_name": "Section A",
                "anchor_key": "section-1",
                "text_content": "chaos attractor",
                "caption": "",
                "display_text": "chaos attractor",
                "token_count": 2,
                "created_at": utc_now(),
                "terms": term_frequencies("chaos attractor"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            },
            {
                "unit_type": "figure",
                "page_number": 1,
                "section_name": "Figure A",
                "anchor_key": "figure-1",
                "text_content": "chaos attractor",
                "caption": "Chaos figure",
                "display_text": "Chaos figure",
                "token_count": 2,
                "created_at": utc_now(),
                "terms": term_frequencies("chaos attractor"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            },
        ],
    )

    monkeypatch.setattr(
        "app.services.search.query_faiss_index",
        lambda _db_path, _query, limit=300: [(1, 0.8), (2, 0.7)],
    )

    results, warning = semantic_search_source_db(
        source_root_id=1,
        source_path="/src",
        db_path=store.db_path,
        query="chaos system",
        unit_types={"figure"},
        vector_min_score=0.0,
    )

    assert warning is None
    assert len(results) == 1
    assert results[0].unit_type == "figure"
