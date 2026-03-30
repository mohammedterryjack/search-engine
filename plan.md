# Plan

## Current Goal

Build `SirChi`, a local document search engine with:

- FastAPI backend
- Google-like web UI with `SirChi` branding
- Docker Compose stack
- SQLite storage
- async ingestion worker
- Docling-based document parsing
- multi-stage retrieval:
  1. inverted index candidate retrieval
  2. BM25 ranking
  3. cross-encoder reranking

## Current State

The project is no longer at the planning-only stage. The following is already implemented:

- FastAPI web app
- source management UI
- local source-path whitelist under `/Users`
- one SQLite database per whitelisted source path
- global SQLite metadata DB for source roots and ingestion jobs
- background worker for ingestion jobs
- Docling-based parsing with no silent text fallback
- term normalization with stop-word removal and lemmatization
- inverted index postings table
- BM25 ranking in Python
- separate reranker service using a real sentence-transformers cross-encoder
- result highlighting
- document open route served through FastAPI

## Implemented Architecture

### Services

- `web`
  - serves HTML UI and search endpoints
  - validates source paths
  - serves source documents inline
- `worker`
  - polls ingestion jobs
  - parses documents with Docling
  - writes `documents`, `content_units`, and `term_postings`
- `reranker`
  - loads a real cross-encoder model
  - reranks top lexical results

### Storage

#### App metadata DB

Used for global coordination:

- `source_roots`
- `ingestion_jobs`

#### Per-source SQLite DB

One DB per whitelist source path:

- `documents`
- `content_units`
- `term_postings`

### Indexed content units

The ingestion layer now attempts to emit:

- `section`
- `figure`
- `table`

Each unit stores:

- `unit_type`
- `page_number`
- `section_name`
- `anchor_key`
- `text_content`
- `caption`
- `display_text`
- token statistics for lexical retrieval

## Retrieval Pipeline

### Step 1: lexical normalization

Implemented in [app/services/tokenize.py](/Users/mohammed/Code/search_engine/app/services/tokenize.py):

- regex tokenization
- lowercase normalization
- lemmatization via `simplemma`
- stop-word removal

### Step 2: inverted index retrieval

- query terms look up matching `content_unit_id`s in `term_postings`
- only normalized non-stopword terms are used

### Step 3: BM25 ranking

- BM25 is computed in Python over candidate content units
- uses indexed term frequencies and content-unit lengths

### Step 4: reranking

- reranker service uses `cross-encoder/ms-marco-MiniLM-L4-v2`
- search no longer silently falls back if reranking fails
- reranker failures surface as explicit search errors in the UI

## UI State

### Homepage

- Google-like centered search box
- `SirChi` branding
- Chi background image styling

### Sources page

- manual absolute-path source entry
- native file picker
- native folder picker where browser support exists
- source clear and delete controls
- per-source indexed-document list
- ingestion job status list

### Results page

- top search bar
- source filters
- ranked result cards
- highlighted terms
- source document links served through the app

## Open-document Behavior

Current behavior:

- result click goes to `/open/{source_root_id}/{content_unit_id}`
- app redirects to `/documents/{source_root_id}/{content_unit_id}`
- FastAPI serves the source file inline
- PDFs append `#page=N` when page metadata is available

Current limitation:

- exact in-document text-position jump is not implemented
- page-level PDF opening is the current best-effort behavior

## Ingestion Behavior

### Current rules

- no silent fallbacks during parsing
- if Docling fails, the job fails explicitly
- unsupported source files are not supposed to be enqueued
- source files are treated as immutable once ingested
- no automatic change detection or periodic reingestion

### Current source assumptions

- whitelist source paths must be under `/Users`
- containers read `/Users` read-only

## Confirmed Remaining Work

The system is working, but it is not finished. These are the main items still left to do.

### 1. Verify and harden real Docling structure extraction

The code now attempts structured extraction for sections, figures, and tables, but this still needs validation against actual stored rows across multiple PDFs.

Needed:

- inspect real `content_units` output for several sample documents
- verify `unit_type` distribution
- verify page numbers
- verify figure captions
- verify table text extraction quality
- adjust extraction logic to the exact Docling schema behavior in practice

### 2. Finish PDF runtime hardening

Docling required extra system libraries during rollout.

Needed:

- confirm current worker image has all required native libs for your PDF set
- confirm parsing succeeds after rebuild on representative PDFs
- add OCR dependencies only if scanned PDFs matter

### 3. Improve job visibility in UI

Current ingestion errors are visible through job status, but the UI can still be improved.

Needed:

- clearer failed-job summaries
- retry controls
- per-source counters for pending/running/failed/done
- better surfaced parser errors in the page itself

### 4. Add tests

Current automated test coverage is minimal.

Needed:

- token normalization tests
- lemmatization tests
- posting creation tests
- BM25 ranking tests
- reranker integration tests
- ingestion job lifecycle tests
- Docling extraction shape tests with fixed sample documents

### 5. Validate native picker behavior

The native folder/file picker is best-effort in a browser context.

Needed:

- verify behavior in your actual preferred browser
- decide whether manual absolute path remains the primary path-entry method
- potentially remove the picker if it proves unreliable

### 6. Add better operational visibility

Needed:

- health/readiness view for web, worker, reranker
- source DB stats
- document counts by source
- searchable unit counts by type

### 7. Improve result presentation

Needed:

- better snippet extraction around matched terms
- more precise page-aware previews
- visible unit type labels for figures/tables when helpful
- cleaner empty/error states

### 8. Possible future retrieval enhancements

Explicitly deferred for now:

- synonym expansion
- fuzzy lexical fallback when exact terms miss
- embedding retrieval fallback
- semantic query expansion

### 9. Make indexing robust to noisy parsed text

Doc parsing can produce lexical noise that hurts exact-term retrieval even when the right content was extracted.

Examples:

- words incorrectly joined together
- words incorrectly split by spaces
- ligature or unicode normalization issues
- line-break artifacts inside words
- OCR-style character substitutions
- table/layout text with unstable token boundaries

Needed:

- add a text-cleaning layer before tokenization
- normalize unicode and ligatures consistently
- repair common intra-word spacing and line-break artifacts
- consider indexing both the raw cleaned token stream and a de-noised auxiliary token stream
- add heuristics for recovering likely split or merged words
- add corpus-level diagnostics for noisy-token rates
- add tests with representative bad parser outputs

Goal:

- make lexical retrieval resilient when Docling output is structurally correct but text segmentation is messy

## Current Risks

### Main risk

The main remaining technical risk is extraction fidelity, not the web app.

Specifically:

- whether Docling emits reliable section/figure/table structure across your PDF corpus
- whether page metadata is consistently present
- whether table extraction quality is good enough for search snippets

### Secondary risk

The reranker is now real, but model startup cost and resource usage still need practical validation on your machine.

## Recommended Next Steps

1. Rebuild the stack after dependency/runtime changes.
2. Reingest one representative PDF-heavy source.
3. Inspect stored `content_units` for:
   - sections
   - figures
   - tables
   - page numbers
4. Verify reranker health and result ordering.
5. Add targeted tests around normalization and Docling extraction.
