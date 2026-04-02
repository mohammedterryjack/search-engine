from __future__ import annotations

import mimetypes
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db.global_store import GlobalStore
from app.db.source_store import SourceStore
from app.services.ingest import list_supported_documents
from app.models import SearchResponse, SearchResult
from app.services.search import SearchPipelineError, search_all_sources
from app.services.vector_store import (
    faiss_path_for_db,
    faiss_reconciliation_report,
    rebuild_faiss_index,
    update_faiss_index,
)
from app.ui import highlight_terms, truncate_text


def nl2br(value: str | None) -> str:
    if not value:
        return ""
    try:
        from markupsafe import Markup
    except ImportError:
        from jinja2 import Markup  # fallback for older jinja
    import html
    escaped = html.escape(value)
    return Markup(escaped.replace("\n", "<br>\n"))


settings = get_settings()
app = FastAPI(title="SearChi")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["highlight_terms"] = highlight_terms
templates.env.filters["truncate_text"] = truncate_text
templates.env.filters["nl2br"] = nl2br

ALLOWED_UNIT_TYPES = ("section", "figure", "table")
ALLOWED_UNIT_TYPE_SET = set(ALLOWED_UNIT_TYPES)
SNIPPET_CHAR_LIMIT = 320


@dataclass(slots=True)
class SearchFilters:
    source_ids: set[int]
    unit_types: set[str]
    vector_min_score: float


class SearchApiFilters(BaseModel):
    source_ids: list[int]
    unit_types: list[str]
    vector_min_score: float


class SearchApiRequest(BaseModel):
    q: str = ""
    source: list[int] = Field(default_factory=list)
    unit_type: list[str] = Field(default_factory=list)
    vector_min_score: float | None = None



class SearchApiResponse(BaseModel):
    results: list[dict[str, object]]
    warning: str | None = None
    error: str | None = None
    filters: SearchApiFilters


def _normalize_unit_types(values: list[str] | None) -> set[str]:
    normalized = {value for value in (values or []) if value in ALLOWED_UNIT_TYPE_SET}
    return normalized if normalized else set(ALLOWED_UNIT_TYPES)


def _build_search_filters(
    source: list[int] | None,
    unit_type: list[str] | None,
    vector_min_score: float | None,
) -> SearchFilters:
    return SearchFilters(
        source_ids=set(source or []),
        unit_types=_normalize_unit_types(unit_type),
        vector_min_score=(
            vector_min_score if vector_min_score is not None else settings.vector_min_score_default
        ),
    )


def _execute_search(query: str, filters: SearchFilters) -> tuple[SearchResponse, str | None]:
    if not query:
        return SearchResponse(results=[]), None
    try:
        response = search_all_sources(
            query,
            source_root_ids=filters.source_ids if filters.source_ids else None,
            unit_types=filters.unit_types,
            vector_min_score=filters.vector_min_score,
        )
        _apply_highlights(response.results, query)
        return response, None
    except SearchPipelineError as exc:
        return SearchResponse(results=[]), str(exc)


def _serialize_search_results(results: list[SearchResult]) -> list[dict[str, object]]:
    return [asdict(result) for result in results]


def _order_unit_types(values: set[str]) -> list[str]:
    return [value for value in ALLOWED_UNIT_TYPES if value in values]


def _apply_highlights(results: list[SearchResult], query: str) -> None:
    if not results:
        return
    for result in results:
        snippet = truncate_text(result.display_text or "", SNIPPET_CHAR_LIMIT)
        result.highlighted_text = highlight_terms(snippet, query)


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


def summarizer_health() -> dict[str, object]:
    if not settings.enable_summarizer:
        return {"status": "disabled"}
    try:
        request = urllib.request.Request(
            f"{settings.summarizer_url}/api/tags",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = response.read().decode("utf-8")
        import json

        data = json.loads(payload)
        models = data.get("models", [])
        found = any(m.get("name") == settings.summarizer_model for m in models)
        return {
            "status": "ok" if found else "model-missing",
            "model_name": settings.summarizer_model,
            "url": settings.summarizer_url,
        }
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}


def ensure_runtime_dirs() -> None:
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
    document_count = 0
    for row in store.list_source_roots():
        stats = SourceStore(Path(str(row["db_path"]))).stats()
        document_count += int(stats["document_count"])
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sources": store.list_source_roots(),
            "document_count": document_count,
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
    filters = _build_search_filters(source, unit_type, vector_min_score)
    search_response, search_error = _execute_search(q, filters)
    search_warning = search_response.warning
    results = search_response.results
    store = GlobalStore()
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "query": q,
            "results": results,
            "sources": store.list_source_roots(),
            "selected_sources": filters.source_ids,
            "selected_unit_types": filters.unit_types,
            "all_unit_types": list(ALLOWED_UNIT_TYPES),
            "vector_min_score": filters.vector_min_score,
            "search_error": search_error,
            "search_warning": search_warning,
            "results_meta_label": None,
            "document_scope_title": None,
        },
    )


@app.post("/api/search", response_model=SearchApiResponse)
async def api_search(payload: SearchApiRequest) -> SearchApiResponse:
    filters = _build_search_filters(
        payload.source,
        payload.unit_type,
        payload.vector_min_score
    )
    search_response, search_error = _execute_search(payload.q, filters)
    return SearchApiResponse(
        results=_serialize_search_results(search_response.results),
        warning=search_response.warning,
        error=search_error,
        filters=SearchApiFilters(
            source_ids=sorted(filters.source_ids),
            unit_types=_order_unit_types(filters.unit_types),
            vector_min_score=filters.vector_min_score,
        ),
    )


class SummarizeSingleRequest(BaseModel):
    text: str


@app.post("/api/summarize-single")
async def api_summarize_single(payload: SummarizeSingleRequest):
    from app.services.summarize import summarize_single_result_stream
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        summarize_single_result_stream(payload.text),
        media_type="text/event-stream"
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
    overall_unit_counts = {"section": 0, "figure": 0, "table": 0}
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
        stats = source_store.stats()
        if stats:
            counts = stats["unit_type_counts"]
            overall_unit_counts["section"] += int(counts.get("section", 0))
            overall_unit_counts["figure"] += int(counts.get("figure", 0))
            overall_unit_counts["table"] += int(counts.get("table", 0))
        documents = []
        for document in source_store.list_documents():
            counts = source_store.document_unit_counts(int(document["id"]))
            documents.append(
                {"record": document, "unit_counts": counts},
            )
        rows.append(
            {
                "source": source,
                "documents": documents,
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
        "overall_unit_counts": overall_unit_counts,
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
    job_counts = store.job_status_counts()
    worker_stale_after_seconds = max(
        settings.poll_seconds * 3 + 3,
        900 if int(job_counts["running"]) > 0 else 0,
    )

    # Gather all worker heartbeats
    worker_heartbeats = []
    for service_name, hb in heartbeats.items():
        if service_name.startswith("worker"):
            status = heartbeat_status(
                str(hb["last_seen"]) if hb else None,
                stale_after_seconds=worker_stale_after_seconds,
            )
            worker_heartbeats.append({
                "name": service_name,
                "status": status,
                "detail": str(hb["detail"]) if hb else "",
                "last_seen": str(hb["last_seen"]) if hb else "",
            })

    # Sort by worker name
    worker_heartbeats.sort(key=lambda w: w["name"])

    # Calculate overall worker status
    if not worker_heartbeats:
        overall_worker_status = "unknown"
        worker_summary = "No workers"
    else:
        ok_count = sum(1 for w in worker_heartbeats if w["status"] == "ok")
        total_count = len(worker_heartbeats)
        if ok_count == total_count:
            overall_worker_status = "ok"
            worker_summary = f"{ok_count}/{total_count} workers ok"
        elif ok_count == 0:
            overall_worker_status = "stale"
            worker_summary = f"0/{total_count} workers ok"
        else:
            overall_worker_status = "partial"
            worker_summary = f"{ok_count}/{total_count} workers ok"

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
            "summarizer_health": summarizer_health(),
            "vector_model_name": settings.vector_model_name,
            "vector_enabled": settings.enable_vector_retrieval,
            "reranker_enabled": settings.enable_reranker,
            "poll_seconds": settings.poll_seconds,
            "web_status": "ok",
            "worker_status": overall_worker_status,
            "worker_summary": worker_summary,
            "workers": worker_heartbeats,
        },
    )


@app.post("/workers/{worker_id}/restart")
async def restart_worker(worker_id: str) -> RedirectResponse:
    store = GlobalStore()
    store.signal_worker_shutdown(worker_id)
    return RedirectResponse("/status", status_code=303)


def _get_document_sections(source_root_id: int, document_id: int) -> tuple[list[SearchResult], str]:
    """Helper to get document sections as SearchResult objects."""
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source_store = SourceStore(Path(str(source_root["db_path"])))
    rows = source_store.content_units_for_document(document_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")

    from app.models import SearchResult

    results = [
        SearchResult(
            source_root_id=source_root_id,
            source_path=str(source_root["source_path"]),
            document_id=int(row["document_id"]),
            content_unit_id=int(row["content_unit_id"]),
            document_path=str(row["document_path"]),
            filename=str(row["filename"]),
            unit_type=str(row["unit_type"]),
            page_number=int(row["page_number"]) if row["page_number"] is not None else None,
            section_name=str(row["section_name"]) if row["section_name"] is not None else "",
            display_text=str(row["display_text"]) if row["display_text"] is not None else "",
            image_mime=row["image_mime"],
            image_data=row["image_data"],
            score=0.0,
        )
        for row in rows
    ]
    filename = str(rows[0]["filename"])
    return results, filename


class DocumentSectionsResponse(BaseModel):
    results: list[dict[str, object]]
    filename: str
    result_count: int


@app.get("/api/sources/{source_root_id}/documents/{document_id}", response_model=DocumentSectionsResponse)
async def api_document_sections(source_root_id: int, document_id: int) -> DocumentSectionsResponse:
    results, filename = _get_document_sections(source_root_id, document_id)
    _apply_highlights(results, "")
    return DocumentSectionsResponse(
        results=_serialize_search_results(results),
        filename=filename,
        result_count=len(results),
    )


@app.get("/sources/{source_root_id}/documents/{document_id}", response_class=HTMLResponse)
async def document_results_view(request: Request, source_root_id: int, document_id: int) -> HTMLResponse:
    store = GlobalStore()
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "query": "",
            "results": [],
            "sources": store.list_source_roots(),
            "selected_sources": {source_root_id},
            "selected_unit_types": {"section", "figure", "table"},
            "all_unit_types": ["section", "figure", "table"],
            "vector_min_score": settings.vector_min_score_default,
            "search_error": None,
            "search_warning": None,
            "document_scope_title": "",
            "results_meta_label": "",
            "source_root_id": source_root_id,
            "document_id": document_id,
            "is_document_view": True,
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


@app.post("/sources/{source_root_id}/sync")
async def sync_source(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")

    source_path = Path(str(source_root["source_path"]))
    source_store = SourceStore(Path(str(source_root["db_path"])))

    supported_documents = list_supported_documents(source_path)
    queued_count = 0
    for document_path in supported_documents:
        if not source_store.has_document(document_path):
            store.enqueue_document(int(source_root["id"]), document_path)
            queued_count += 1

    if queued_count > 0:
        success_message = f"Found {queued_count} new document(s) and queued for ingestion."
    else:
        success_message = "No new documents found."
    return sources_redirect(success=success_message)


@app.post("/sources/{source_root_id}/retry-failed")
async def retry_failed_source_jobs(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")

    store.retry_failed_jobs(source_root_id)
    return sources_redirect(success="Failed jobs have been queued for retry.")


@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int) -> RedirectResponse:
    store = GlobalStore()
    store.retry_job(job_id)
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
