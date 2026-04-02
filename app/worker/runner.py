from __future__ import annotations

import gc
import os
import socket
import time
from pathlib import Path
import psutil

from app.config import get_settings
from app.db.global_store import GlobalStore, utc_now
from app.db.source_store import SourceStore
from app.services.ingest import build_units, parse_document
from app.services.vector_store import get_embedding_model, rebuild_faiss_index, update_faiss_index


def log_memory(label: str):
    """Log current memory usage."""
    process = psutil.Process()
    mem_info = process.memory_info()
    mem_mb = mem_info.rss / 1024 / 1024
    print(f"[MEMORY] {label}: {mem_mb:.1f} MB")


def get_worker_id() -> str:
    """Get a unique identifier for this worker instance."""
    hostname = socket.gethostname()
    if hostname.startswith("search-engine-worker-"):
        return hostname.replace("search-engine-", "")
    container_id = os.environ.get("HOSTNAME", "")
    if container_id:
        return f"worker-{container_id[:12]}"
    return "worker-unknown"


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

    log_memory("Startup - before Docling")
    ensure_docling_available()
    log_memory("Startup - after Docling")

    if settings.enable_vector_retrieval:
        ensure_vector_model_available()
        log_memory("Startup - after vector model")

    store = GlobalStore()

    # On startup, immediately recover any orphaned jobs from crashed workers
    recovered = store.recover_stale_jobs(stale_after_seconds=0)
    if recovered > 0:
        print(f"Worker {get_worker_id()} recovered {recovered} orphaned job(s) on startup")

    log_memory("Ready to process jobs")

    while True:
        # Recover stale jobs on each iteration (lightweight check)
        store.recover_stale_jobs(stale_after_seconds=900)
        job = store.take_next_job()
        if job is None:
            time.sleep(settings.poll_seconds)
            continue

        try:
            log_memory(f"Starting job: {job['document_path']}")

            source_root = store.get_source_root(int(job["source_root_id"]))
            if source_root is None:
                raise RuntimeError("source root not found")
            source_store = SourceStore(Path(str(source_root["db_path"])))
            document_path = Path(str(job["document_path"]))

            # Parse document
            log_memory("Before parsing document")
            parsed = parse_document(document_path)
            log_memory(f"After parsing - got {len(parsed)} units")

            page_count = max((unit.page_number or 1) for unit in parsed) if parsed else 0

            # Build units and convert to dicts
            log_memory("Before building units")
            units = build_units(parsed)
            log_memory(f"After building - {len(units)} units")

            # Free parsed data immediately after building units
            del parsed
            gc.collect()
            log_memory("After freeing parsed data")

            # Create/update document record
            document_id = source_store.upsert_document(
                document_path=document_path,
                status="indexed",
                page_count=page_count,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            old_content_unit_ids = source_store.document_content_unit_ids(document_id)

            # Write all units to database
            log_memory("Before writing to DB")
            source_store.replace_content_units(document_id, units)
            log_memory("After writing to DB")

            # Free units from memory immediately after writing
            del units
            gc.collect()
            log_memory("After freeing units")
            if settings.enable_vector_retrieval:
                log_memory("Before vector indexing")
                db_path = Path(str(source_root["db_path"]))
                new_rows = source_store.document_content_unit_texts(document_id)
                log_memory(f"Got {len(new_rows)} rows for embedding")

                if old_content_unit_ids or new_rows:
                    try:
                        update_faiss_index(
                            db_path,
                            remove_ids=old_content_unit_ids,
                            add_rows=new_rows,
                        )
                    except Exception:
                        rebuild_faiss_index(db_path, source_store.all_content_unit_texts())
                log_memory("After vector indexing")

            store.mark_job_done(int(job["id"]))
            log_memory("Job completed successfully")
        except Exception as exc:
            log_memory(f"Job failed: {exc}")
            store.mark_job_failed(int(job["id"]), str(exc))
        finally:
            # Force garbage collection after each job to free memory
            gc.collect()
            log_memory("After final GC")


if __name__ == "__main__":
    run_forever()
