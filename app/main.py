from __future__ import annotations

import mimetypes
import os
import shutil
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings, legacy_repo_data_dir
from app.db.global_store import GlobalStore
from app.db.source_store import SourceStore
from app.services.ingest import list_supported_documents
from app.services.search import SearchPipelineError, search_all_sources
from app.services.vector_store import (
    faiss_path_for_db,
    faiss_reconciliation_report,
    rebuild_faiss_index,
    update_faiss_index,
)
from app.ui import highlight_terms, truncate_text


settings = get_settings()
app = FastAPI(title="SearChi")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["highlight_terms"] = highlight_terms
templates.env.filters["truncate_text"] = truncate_text


def format_bytes(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"


def reranker_health() -> dict[str, object]:
    if not settings.enable_reranker:
        return {"status": "disabled"}
    try:
        request = urllib.request.Request(
            f"{settings.reranker_url}/internal/health",
            headers={"X-Searchi-Status-Token": settings.status_token},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = response.read().decode("utf-8")
        import json

        data = json.loads(payload)
        return {
            "status": str(data.get("status", "ok")),
            "model_name": str(data.get("model_name", "")),
            "device": str(data.get("device", "")),
        }
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}


def ensure_runtime_dirs() -> None:
    legacy_data = legacy_repo_data_dir()
    if (
        "SEARCHY_DATA_DIR" not in os.environ
        and legacy_data.exists()
        and not settings.data_dir.exists()
        and legacy_data != settings.data_dir
    ):
        settings.data_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_data), str(settings.data_dir))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.app_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.source_db_dir.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs()
    GlobalStore().touch_service_heartbeat("web", "startup")


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def heartbeat_status(last_seen: str | None, *, stale_after_seconds: float) -> str:
    timestamp = parse_iso_timestamp(last_seen)
    if timestamp is None:
        return "unknown"
    age = (datetime.now(UTC) - timestamp).total_seconds()
    return "ok" if age <= stale_after_seconds else "stale"


@app.exception_handler(404)
async def not_found(request: Request, _exc: StarletteHTTPException) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        status_code=404,
    )


def sources_redirect(
    *,
    error: str | None = None,
    success: str | None = None,
    source_path: str | None = None,
) -> RedirectResponse:
    params: dict[str, str] = {}
    if error:
        params["error"] = error
    if success:
        params["success"] = success
    if source_path:
        params["source_path"] = source_path
    url = "/sources"
    if params:
        url += f"?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=303)


def resolve_source_path(raw_source_path: str) -> tuple[Path, str]:
    input_path = Path(raw_source_path).expanduser()
    if not input_path.is_absolute():
        raise FileNotFoundError("Use an absolute path.")
    input_path = input_path.resolve()
    try:
        input_path.relative_to(settings.allowed_source_root)
    except ValueError as exc:
        raise FileNotFoundError(
            f"Path must be under {settings.allowed_source_root}."
        ) from exc
    if not input_path.exists():
        raise FileNotFoundError("Source path does not exist.")
    return input_path, str(input_path)


def get_content_unit(source_root_id: int, content_unit_id: int) -> tuple[Path, object]:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source_store = SourceStore(Path(str(source_root["db_path"])))
    row = source_store.content_unit_by_id(content_unit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Result not found")
    document_path = Path(str(row["document_path"]))
    if not document_path.exists():
        raise HTTPException(status_code=404, detail="Source document is missing")
    return document_path, row


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    store = GlobalStore()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sources": store.list_source_roots(),
            "jobs": store.list_jobs()[:10],
            "default_vector_min_score": settings.vector_min_score_default,
            "all_unit_types": ["section", "figure", "table"],
        },
    )


@app.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = "",
    source: list[int] | None = None,
    unit_type: list[str] | None = None,
    vector_min_score: float | None = None,
) -> HTMLResponse:
    selected = set(source or [])
    allowed_unit_types = {"section", "figure", "table"}
    selected_unit_types = {
        value for value in (unit_type or sorted(allowed_unit_types)) if value in allowed_unit_types
    }
    search_error = None
    search_warning = None
    results = []
    effective_vector_min_score = (
        vector_min_score if vector_min_score is not None else settings.vector_min_score_default
    )
    if q:
        try:
            response = search_all_sources(
                q,
                selected if selected else None,
                unit_types=selected_unit_types if selected_unit_types else allowed_unit_types,
                vector_min_score=effective_vector_min_score,
            )
            results = response.results
            search_warning = response.warning
        except SearchPipelineError as exc:
            search_error = str(exc)
    store = GlobalStore()
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "query": q,
            "results": results,
            "sources": store.list_source_roots(),
            "selected_sources": selected,
            "selected_unit_types": selected_unit_types,
            "all_unit_types": ["section", "figure", "table"],
            "vector_min_score": effective_vector_min_score,
            "search_error": search_error,
            "search_warning": search_warning,
        },
    )


@app.get("/sources", response_class=HTMLResponse)
async def sources_view(
    request: Request,
    error: str | None = None,
    success: str | None = None,
    source_path: str = "",
) -> HTMLResponse:
    store = GlobalStore()
    store.touch_service_heartbeat("web", "sources")
    rows = []
    global_job_counts = store.job_status_counts()
    running_jobs = [job for job in store.list_jobs() if str(job["status"]) == "running"][:10]
    for source in store.list_source_roots():
        source_store = SourceStore(Path(str(source["db_path"])))
        db_path = Path(str(source["db_path"]))
        vector_report = faiss_reconciliation_report(db_path, source_store.all_content_unit_texts())
        job_counts = store.job_status_counts(int(source["id"]))
        vector_status = str(vector_report["status"])
        if vector_status == "mismatch" and (job_counts["pending"] or job_counts["running"]):
            vector_status = "syncing"
        rows.append(
            {
                "source": source,
                "documents": source_store.list_documents(),
                "jobs": store.list_jobs(int(source["id"]))[:10],
                "job_counts": job_counts,
                "stats": source_store.stats(),
                "vector_report": vector_report,
                "vector_status": vector_status,
            }
        )
    return templates.TemplateResponse(
        request,
        "sources.html",
        {
            "rows": rows,
            "global_job_counts": global_job_counts,
            "running_jobs": running_jobs,
            "indexing_active": bool(global_job_counts["running"] or global_job_counts["pending"]),
            "reranker_health": reranker_health(),
            "error": error,
            "success": success,
            "source_path": source_path,
            "allowed_source_root": settings.allowed_source_root,
            "format_bytes": format_bytes,
        },
    )


@app.get("/status", response_class=HTMLResponse)
async def status_view(request: Request) -> HTMLResponse:
    store = GlobalStore()
    store.touch_service_heartbeat("web", "status")
    source_rows = store.list_source_roots()
    total_documents = 0
    total_content_units = 0
    total_embeddings = 0
    total_postings = 0
    for row in source_rows:
        stats = SourceStore(Path(str(row["db_path"]))).stats()
        total_documents += int(stats["document_count"])
        total_content_units += int(stats["content_unit_count"])
        total_embeddings += int(stats["embedding_count"])
        total_postings += int(stats["term_posting_count"])
    heartbeats = store.service_heartbeats()
    worker_heartbeat = heartbeats.get("worker")
    job_counts = store.job_status_counts()
    worker_stale_after_seconds = max(
        settings.poll_seconds * 3 + 3,
        900 if int(job_counts["running"]) > 0 else 0,
    )
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "job_counts": job_counts,
            "source_count": len(source_rows),
            "document_count": total_documents,
            "content_unit_count": total_content_units,
            "embedding_count": total_embeddings,
            "term_posting_count": total_postings,
            "reranker_health": reranker_health(),
            "vector_model_name": settings.vector_model_name,
            "vector_enabled": settings.enable_vector_retrieval,
            "reranker_enabled": settings.enable_reranker,
            "poll_seconds": settings.poll_seconds,
            "web_status": "ok",
            "worker_status": heartbeat_status(
                str(worker_heartbeat["last_seen"]) if worker_heartbeat else None,
                stale_after_seconds=worker_stale_after_seconds,
            ),
            "worker_detail": str(worker_heartbeat["detail"]) if worker_heartbeat else "",
        },
    )


@app.post("/sources")
async def add_source(request: Request) -> RedirectResponse:
    form = await request.form()
    source_path = str(form.get("source_path", "")).strip()
    if not source_path:
        return sources_redirect(error="Source path is required.")
    try:
        path, display_source_path = resolve_source_path(source_path)
    except FileNotFoundError as exc:
        return sources_redirect(error=str(exc), source_path=source_path)

    store = GlobalStore()
    source_root = store.ensure_source_root(path)
    source_store = SourceStore(Path(str(source_root["db_path"])))
    source_store._init_db()

    supported_documents = list_supported_documents(path)
    queued_count = 0
    for document_path in supported_documents:
        if not source_store.has_document(document_path):
            store.enqueue_document(int(source_root["id"]), document_path)
            queued_count += 1

    success_message = (
        f"Tracked source {display_source_path}. "
        f"Found {len(supported_documents)} supported document(s) and queued {queued_count} new ingestion job(s)."
    )
    return sources_redirect(success=success_message, source_path=display_source_path)


@app.post("/sources/{source_root_id}/clear")
async def clear_source(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source_store = SourceStore(Path(str(source_root["db_path"])))
    db_path = Path(str(source_root["db_path"]))
    removed_ids = source_store.clear_with_content_ids()
    if removed_ids:
        update_faiss_index(db_path, remove_ids=removed_ids)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_root_id}/retry-failed")
async def retry_failed_source_jobs(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    if store.get_source_root(source_root_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
    store.retry_failed_jobs(source_root_id)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int) -> RedirectResponse:
    store = GlobalStore()
    store.retry_job(job_id)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_root_id}/repair-index")
async def repair_source_index(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    db_path = Path(str(source_root["db_path"]))
    source_store = SourceStore(db_path)
    rebuild_faiss_index(db_path, source_store.all_content_unit_texts())
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_root_id}/delete")
async def delete_source(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.delete_source_root(source_root_id)
    if source_root is not None:
        db_path = Path(str(source_root["db_path"]))
        if db_path.exists():
            db_path.unlink()
        faiss_path = faiss_path_for_db(db_path)
        if faiss_path.exists():
            faiss_path.unlink()
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_root_id}/documents/{document_id}/delete")
async def delete_document(source_root_id: int, document_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    db_path = Path(str(source_root["db_path"]))
    source_store = SourceStore(db_path)
    removed_ids = source_store.delete_document_with_content_ids(document_id)
    if removed_ids:
        update_faiss_index(db_path, remove_ids=removed_ids)
    return RedirectResponse(url="/sources", status_code=303)


@app.get("/open/{source_root_id}/{content_unit_id}")
async def open_result(source_root_id: int, content_unit_id: int) -> RedirectResponse:
    document_path, row = get_content_unit(source_root_id, content_unit_id)
    target = f"/documents/{source_root_id}/{content_unit_id}"
    if document_path.suffix.lower() == ".pdf" and row["page_number"]:
        target += f"#page={int(row['page_number'])}"
    return RedirectResponse(url=target, status_code=307)


@app.get("/documents/{source_root_id}/{content_unit_id}")
async def serve_document(source_root_id: int, content_unit_id: int) -> FileResponse:
    document_path, _row = get_content_unit(source_root_id, content_unit_id)
    media_type, _encoding = mimetypes.guess_type(document_path.name)
    return FileResponse(
        path=document_path,
        media_type=media_type or "application/octet-stream",
        filename=document_path.name,
        content_disposition_type="inline",
    )
