from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db.global_store import GlobalStore
from app.db.source_store import SourceStore
from app.services.ingest import list_supported_documents
from app.services.search import search_all_sources
from app.ui import highlight_terms, truncate_text


settings = get_settings()
app = FastAPI(title="Searchy")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["highlight_terms"] = highlight_terms
templates.env.filters["truncate_text"] = truncate_text


def ensure_runtime_dirs() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.app_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.source_db_dir.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs()
    GlobalStore()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    store = GlobalStore()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sources": store.list_source_roots(),
            "jobs": store.list_jobs()[:10],
        },
    )


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", source: list[int] | None = None) -> HTMLResponse:
    selected = set(source or [])
    results = search_all_sources(q, selected if selected else None) if q else []
    store = GlobalStore()
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "query": q,
            "results": results,
            "sources": store.list_source_roots(),
            "selected_sources": selected,
        },
    )


@app.get("/sources", response_class=HTMLResponse)
async def sources_view(request: Request) -> HTMLResponse:
    store = GlobalStore()
    rows = []
    for source in store.list_source_roots():
        source_store = SourceStore(Path(str(source["db_path"])))
        rows.append(
            {
                "source": source,
                "documents": source_store.list_documents(),
                "jobs": store.list_jobs(int(source["id"]))[:10],
            }
        )
    return templates.TemplateResponse(request, "sources.html", {"rows": rows})


@app.post("/sources")
async def add_source(request: Request) -> RedirectResponse:
    form = await request.form()
    source_path = str(form.get("source_path", "")).strip()
    if not source_path:
        raise HTTPException(status_code=400, detail="Source path is required")
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=400, detail="Source path does not exist")

    store = GlobalStore()
    source_root = store.ensure_source_root(path)
    source_store = SourceStore(Path(str(source_root["db_path"])))
    source_store._init_db()

    for document_path in list_supported_documents(path):
        if not source_store.has_document(document_path):
            store.enqueue_document(int(source_root["id"]), document_path)

    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_root_id}/clear")
async def clear_source(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source_store = SourceStore(Path(str(source_root["db_path"])))
    source_store.clear()
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_root_id}/delete")
async def delete_source(source_root_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.delete_source_root(source_root_id)
    if source_root is not None:
        db_path = Path(str(source_root["db_path"]))
        if db_path.exists():
            db_path.unlink()
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{source_root_id}/documents/{document_id}/delete")
async def delete_document(source_root_id: int, document_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source_store = SourceStore(Path(str(source_root["db_path"])))
    source_store.delete_document(document_id)
    return RedirectResponse(url="/sources", status_code=303)


@app.get("/open/{source_root_id}/{content_unit_id}")
async def open_result(source_root_id: int, content_unit_id: int) -> RedirectResponse:
    store = GlobalStore()
    source_root = store.get_source_root(source_root_id)
    if source_root is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source_store = SourceStore(Path(str(source_root["db_path"])))
    row = source_store.content_unit_by_id(content_unit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Result not found")

    document_path = Path(str(row["document_path"]))
    if document_path.suffix.lower() == ".pdf" and row["page_number"]:
        target = f"file://{quote(str(document_path))}#page={int(row['page_number'])}"
    else:
        target = f"file://{quote(str(document_path))}"
    return RedirectResponse(url=target, status_code=307)
