from __future__ import annotations

import time
from pathlib import Path

from app.config import get_settings
from app.db.global_store import GlobalStore, utc_now
from app.db.source_store import SourceStore
from app.services.ingest import build_units, parse_document
from app.services.vector_store import get_embedding_model, rebuild_faiss_index, update_faiss_index


def ensure_docling_available() -> None:
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Worker startup failed because Docling is not installed or could not be imported."
        ) from exc

    _ = DocumentConverter


def ensure_vector_model_available() -> None:
    _ = get_embedding_model()


def run_forever() -> None:
    settings = get_settings()
    ensure_docling_available()
    if settings.enable_vector_retrieval:
        ensure_vector_model_available()
    store = GlobalStore()
    while True:
        store.touch_service_heartbeat("worker", "polling")
        job = store.take_next_job()
        if job is None:
            time.sleep(settings.poll_seconds)
            continue
        try:
            store.touch_service_heartbeat("worker", f"indexing {job['document_path']}")
            source_root = store.get_source_root(int(job["source_root_id"]))
            if source_root is None:
                raise RuntimeError("source root not found")
            source_store = SourceStore(Path(str(source_root["db_path"])))
            document_path = Path(str(job["document_path"]))
            parsed = parse_document(document_path)
            units = build_units(parsed)
            document_id = source_store.upsert_document(
                document_path=document_path,
                status="indexed",
                page_count=max((unit.page_number or 1) for unit in parsed) if parsed else 0,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            old_content_unit_ids = source_store.document_content_unit_ids(document_id)
            source_store.replace_content_units(document_id, units)
            if settings.enable_vector_retrieval:
                db_path = Path(str(source_root["db_path"]))
                new_rows = source_store.document_content_unit_texts(document_id)
                if old_content_unit_ids or new_rows:
                    try:
                        update_faiss_index(
                            db_path,
                            remove_ids=old_content_unit_ids,
                            add_rows=new_rows,
                        )
                    except Exception:
                        rebuild_faiss_index(db_path, source_store.all_content_unit_texts())
            store.mark_job_done(int(job["id"]))
            store.touch_service_heartbeat("worker", f"done {job['document_path']}")
        except Exception as exc:
            store.mark_job_failed(int(job["id"]), str(exc))
            store.touch_service_heartbeat("worker", f"failed {job['document_path']}")


if __name__ == "__main__":
    run_forever()
