from __future__ import annotations

from pathlib import Path

from app.db.global_store import GlobalStore, utc_now
from app.db.source_store import SourceStore
from app.services.tokenize import term_frequencies
from app.services.vector_store import faiss_path_for_db, update_faiss_index


def configure_env(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("SEARCHY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SEARCHY_APP_DB_PATH", str(data_dir / "app.sqlite3"))
    monkeypatch.setenv("SEARCHY_SOURCE_DB_DIR", str(data_dir / "source_dbs"))
    monkeypatch.setenv("SEARCHY_ALLOWED_SOURCE_ROOT", str(tmp_path))


def test_global_store_job_retry_lifecycle(monkeypatch, tmp_path: Path) -> None:
    configure_env(monkeypatch, tmp_path)
    source_path = tmp_path / "docs"
    source_path.mkdir()

    store = GlobalStore()
    source_row = store.ensure_source_root(source_path)
    doc_path = source_path / "sample.pdf"
    doc_path.write_text("placeholder")
    store.enqueue_document(int(source_row["id"]), doc_path)

    job = store.take_next_job()
    assert job is not None
    assert str(job["status"]) == "running"

    store.mark_job_failed(int(job["id"]), "boom")
    failed = store.list_jobs(int(source_row["id"]))[0]
    assert str(failed["status"]) == "failed"
    assert str(failed["error_message"]) == "boom"

    store.retry_job(int(job["id"]))
    retried = store.list_jobs(int(source_row["id"]))[0]
    assert str(retried["status"]) == "pending"
    assert retried["error_message"] is None


def test_source_store_replace_units_and_stats(monkeypatch, tmp_path: Path) -> None:
    configure_env(monkeypatch, tmp_path)
    doc_path = tmp_path / "docs" / "paper.pdf"
    doc_path.parent.mkdir()
    doc_path.write_text("alpha beta alpha\n")

    store = SourceStore(tmp_path / "source.sqlite3")
    document_id = store.upsert_document(
        document_path=doc_path,
        status="indexed",
        page_count=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    created_at = utc_now()
    store.replace_content_units(
        document_id,
        [
            {
                "unit_type": "section",
                "page_number": 1,
                "section_name": "Intro",
                "anchor_key": "section-1",
                "text_content": "alpha beta alpha",
                "caption": "",
                "display_text": "alpha beta alpha",
                "token_count": 3,
                "created_at": created_at,
                "terms": term_frequencies("alpha beta alpha"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            },
            {
                "unit_type": "figure",
                "page_number": 2,
                "section_name": "Figure 1",
                "anchor_key": "figure-1",
                "text_content": "phase portrait",
                "caption": "Lorenz attractor",
                "display_text": "Lorenz attractor phase portrait",
                "token_count": 4,
                "created_at": created_at,
                "terms": term_frequencies("Lorenz attractor phase portrait"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            },
        ],
    )

    stats = store.stats()
    assert stats["document_count"] == 1
    assert stats["content_unit_count"] == 2
    assert stats["embedding_count"] == 2
    assert stats["term_posting_count"] >= 2
    assert stats["unit_type_counts"]["section"] == 1
    assert stats["unit_type_counts"]["figure"] == 1
    assert store.document_content_unit_ids(document_id)
    assert len(store.document_content_unit_texts(document_id)) == 2

    faiss_path_for_db(store.db_path).write_bytes(b"index")
    stats_with_index = store.stats()
    assert stats_with_index["faiss_exists"] is True
    assert stats_with_index["faiss_size_bytes"] == 5


def test_delete_document_can_drive_faiss_cleanup(monkeypatch, tmp_path: Path) -> None:
    configure_env(monkeypatch, tmp_path)
    doc_path = tmp_path / "docs" / "paper.pdf"
    doc_path.parent.mkdir()
    doc_path.write_text("alpha beta alpha\n")

    store = SourceStore(tmp_path / "source.sqlite3")
    document_id = store.upsert_document(
        document_path=doc_path,
        status="indexed",
        page_count=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    created_at = utc_now()
    store.replace_content_units(
        document_id,
        [
            {
                "unit_type": "section",
                "page_number": 1,
                "section_name": "Intro",
                "anchor_key": "section-1",
                "text_content": "alpha beta alpha",
                "caption": "",
                "display_text": "alpha beta alpha",
                "token_count": 3,
                "created_at": created_at,
                "terms": term_frequencies("alpha beta alpha"),
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            }
        ],
    )
    update_faiss_index(store.db_path, add_rows=store.document_content_unit_texts(document_id))
    assert faiss_path_for_db(store.db_path).exists()

    removed_ids = store.delete_document_with_content_ids(document_id)
    update_faiss_index(store.db_path, remove_ids=removed_ids)

    assert store.list_documents() == []
    assert faiss_path_for_db(store.db_path).exists() is False
