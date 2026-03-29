from __future__ import annotations

import time
from pathlib import Path

from app.config import get_settings
from app.db.global_store import GlobalStore, utc_now
from app.db.source_store import SourceStore
from app.services.ingest import build_units, parse_document


def run_forever() -> None:
    settings = get_settings()
    store = GlobalStore()
    while True:
        job = store.take_next_job()
        if job is None:
            time.sleep(settings.poll_seconds)
            continue
        try:
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
            source_store.replace_content_units(document_id, units)
            store.mark_job_done(int(job["id"]))
        except Exception as exc:
            store.mark_job_failed(int(job["id"]), str(exc))


if __name__ == "__main__":
    run_forever()
