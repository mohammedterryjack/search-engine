# Plan

## Goal

Build a local document search engine with:

- FastAPI backend
- Simple web UI with a Google-like search page and results page
- Lightweight Dockerfile and `docker-compose.yml`
- Async ingestion pipeline that parses documents with Docling
- SQLite-backed section-level retrieval
- Multi-stage ranking:
  1. inverted index candidate retrieval
  2. BM25 top 100 selection
  3. cross-encoder reranking for final ordering

This is a greenfield reset. The current repo should be treated as disposable implementation history unless a small piece is explicitly kept.

## Product Scope

### Core user flows

1. User opens the web app and sees a minimal search box.
2. User submits a query.
3. System retrieves relevant sections, figures, and tables from indexed documents.
4. Results show:
   - source document path
   - page number
   - section name
   - stored text or caption
   - highlighted query terms
   - a link that opens the source document at the correct page
5. User adds a whitelist source path.
6. System ingests all supported documents in that file or directory path.
7. Async worker parses documents with Docling and stores extracted units in SQLite.

### Indexed content units

Each extracted unit becomes a searchable record:

- document section
- figure caption
- table caption
- optionally standalone table text if Docling exposes it cleanly

## Proposed Architecture

### Services

- `web`: FastAPI app serving API and HTML UI
- `worker`: async ingestion worker
- `reranker`: local cross-encoder scoring service or isolated container

### Storage model

- One SQLite database file per whitelisted source path
- Each source path is isolated from the others at the storage layer
- Search runs across all source databases by default, with source filtering in the UI

### High-level flow

1. User adds a whitelist source path.
2. Web app creates or loads the SQLite database for that source.
3. Web app creates ingestion jobs for all supported documents under that source.
4. Worker reads jobs and runs Docling.
5. Worker splits output into searchable units.
6. Worker tokenizes units and writes:
   - document metadata
   - content units
   - inverted index postings
7. Query API tokenizes the search input.
8. Inverted index fetches candidate content units across source DBs.
9. BM25 ranks candidates and keeps top 100.
10. Cross-encoder reranks those 100.
11. UI renders results with highlights and source links.

## Data Model

### `source_roots`

Registry table in the app metadata database.

- `id`
- `source_path`
- `source_type` (`file`, `directory`)
- `db_path`
- `status`
- `created_at`

### `documents`

- `id`
- `source_path`
- `filename`
- `file_checksum`
- `status`
- `page_count`
- `created_at`
- `updated_at`

### `content_units`

One row per section, figure, or table.

- `id`
- `document_id`
- `unit_type` (`section`, `figure`, `table`)
- `page_number`
- `section_name`
- `anchor_key`
- `text_content`
- `caption`
- `display_text`
- `token_count`
- `created_at`

`display_text` is the canonical field used by retrieval and UI. For sections it will usually mirror body text; for figures/tables it will usually be the caption or extracted text fallback.

### `term_postings`

This is the explicit inverted index table.

- `term`
- `content_unit_id`
- `term_frequency`
- `positions` or compact positional metadata if needed

Composite indexes:

- `(term, content_unit_id)`
- `(content_unit_id, term)`

### `ingestion_jobs`

- `id`
- `source_root_id`
- `document_id`
- `status`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

### Duplicate handling

- A document is identified logically by its absolute file path within a source
- A `documents` row prevents duplicate ingestion of the same file
- There is no automatic change detection
- If a file changes on disk after ingestion, the system ignores that change unless the user removes the document and ingests again

## Search Pipeline

### Step 1: candidate retrieval

- Normalize query terms
- Remove stop words
- Use `term_postings` to fetch matching `content_unit_id`s
- Score initial candidates with term frequency and coverage

### Step 2: BM25 ranking

- Run BM25 over candidate units using stored term frequencies and document-length statistics
- Keep top 100 units

### Step 3: cross-encoder reranking

- Use a lightweight sentence-transformers cross-encoder
- Input: `(query, display_text)`
- Return final ranked result list

### Result rendering

Each result should include:

- title line from `section_name` or a derived label
- source path
- page number
- snippet from `display_text`
- highlighted query terms
- open link to the source document at the correct page

## Docling Ingestion Plan

### Parsing

- Use Docling to extract:
  - document sections
  - figures and captions
  - tables and captions
  - any other formats Docling supports
  - page references when available

### Normalization

- Convert parsed output into `content_units`
- Preserve page number when Docling provides it
- Derive `section_name` from heading hierarchy
- Produce stable `anchor_key` values for deterministic linking
- Store every section, figure, and table as its own row without additional semantic merging

### Async execution

- Use a simple async worker with SQLite-backed job polling
- Optimize for smooth local behavior instead of queue-system complexity
- Avoid Redis/Celery in v1

## Web App

### UI shape

- Homepage:
  - centered `Searchy` branding
  - large search box
  - minimal controls
- Results page:
  - search bar at top
  - ranked results list
  - path, page number, and snippet per result
  - source filter controls
  - management view for clearing a source DB or removing a single document

### Implementation approach

- FastAPI serves both API and server-rendered HTML
- Jinja templates plus minimal CSS/JS
- Match Google’s layout and visual rhythm as closely as practical while branding it as `Searchy`
- Avoid a separate frontend framework in v1

## Open-document Links

We need a practical local strategy for opening documents at the correct page.

### v1 approach

- Store absolute local source path
- Generate links through a FastAPI route such as `/open/{content_unit_id}`
- Route resolves the file path, page number, and anchor metadata
- For PDFs, append `#page=N` for browser-supported viewers
- Exact in-document section jump is best-effort; page-level opening is the reliable baseline

Note:
Direct page-specific opening behavior can vary by browser and local file handling. We should treat this as a compatibility area to verify early.

## Docker Plan

### Containers

- `web`
- `worker`
- `reranker`

### Requirements

- small Python base image
- no unnecessary build tooling in final runtime image
- mounted local document directory for ingestion
- persistent app data volume for SQLite databases and model caches

### Compose responsibilities

- run API
- run worker
- run reranker service when enabled
- mount project source for local development
- mount document source directory

## Proposed Initial Tech Stack

- Python 3.11+
- FastAPI
- Jinja2
- SQLAlchemy or direct `sqlite3`
- SQLite
- Docling
- `rank-bm25` or in-house BM25 implementation
- sentence-transformers cross-encoder
- Uvicorn

## Repo Reset Plan

### Phase 0

- Create `plan.md`
- Confirm scope of the reset

### Phase 1

- Remove current terminal UI implementation and old indexing code
- Replace project structure with:
  - `app/api`
  - `app/services`
  - `app/db`
  - `app/templates`
  - `app/static`
  - `app/worker`

### Phase 2

- Add Dockerfile and compose stack for web, worker, and db
- Add FastAPI app skeleton
- Add SQLite schema creation and per-source DB management

### Phase 3

- Implement document ingestion job flow with Docling
- Store parsed units and inverted index postings

### Phase 4

- Implement search pipeline:
  - candidate lookup
  - BM25
  - reranker

### Phase 5

- Implement UI and result highlighting
- Implement open-document route

### Phase 6

- Add tests for:
  - tokenization
  - posting creation
  - BM25 ranking
  - reranker integration boundaries
  - ingestion job lifecycle

## Risks And Early Decisions

### Open questions to settle early

- Exact Docling output shape for page-aware sections, figures, and tables
- Whether figure/table extraction reliably includes page numbers
- Which cross-encoder model is light enough for local Docker usage
- Whether exact local open-at-location behavior is possible beyond page-level PDF jumps

### Main risk

The biggest implementation risk is not the web app. It is the extraction fidelity from Docling and the cost of local reranking. We should validate both before spending time polishing the UI.

## Recommended Build Order

1. Reset repo structure.
2. Stand up FastAPI + worker + reranker in Docker Compose.
3. Create app metadata DB and per-source SQLite DB layout.
4. Prove Docling ingestion on one sample document.
5. Persist `documents`, `content_units`, and `term_postings`.
6. Build raw retrieval across all source DBs.
7. Add BM25.
8. Add reranker.
9. Add Google-like `Searchy` UI and highlighting.
10. Add document removal and source-clear management views.
11. Add open-at-page links.
12. Harden with tests.
