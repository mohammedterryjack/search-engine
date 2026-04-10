# Architecture

This document reflects the current `SearChi` architecture as implemented, including known simplifications and open gaps.

## System Diagram

```text
                               +----------------------+
                               | Browser              |
                               | SearChi UI           |
                               | search / sources     |
                               +----------+-----------+
                                          |
                                          v
                               +----------------------+
                               | FastAPI Web App      |
                               | HTML + API + docs    |
                               | /search /sources     |
                               | /open /documents     |
                               +----+------------+----+
                                    |            |
                        add source   |            | search query
                                    |            |
                                    v            v
                        +------------------+   +----------------------+
                        | App Metadata DB  |   | Query Pipeline       |
                        | SQLite           |   | normalize + lemma    |
                        | source_roots     |   | lexical retrieval    |
                        | ingestion_jobs   |   | vector retrieval     |
                        +--------+---------+   | fuse -> rerank       |
                                 |             +----+------^-------+
                                 |                  |      |
                                 v                  v      |
                        +------------------+   +----------------------+
                        | Async Worker     |   | Reranker Service     |
                        | Docling parse    |   | cross-encoder        |
                        | build units      |   | ms-marco MiniLM      |
                        +--------+---------+   +----------+-----------+
                                 |                        |
                                 v                        v
                     +----------------------------+   +----------------------+
                     | Per-Source SQLite DB       |   | Summarizer Service   |
                     | one DB per whitelist path  |   | Ollama               |
                     |                            |   | Qwen + GPT OSS       |
                     | documents                  |   +----------------------+
                     | content_units              |
                     | term_postings              |
                     | content_embeddings         |
                     +-------------+--------------+
                                   |
                                   v
                     +----------------------------+
                     | Per-Source FAISS Index     |
                     | vectors keyed by           |
                     | content_unit_id            |
                     +-------------+--------------+
                                   |
                                   v
                     +----------------------------+
                     | Local Filesystem Sources   |
                     | /Users/...                 |
                     | PDFs, MD, DOCX, etc.       |
                     +----------------------------+
```

## Ingestion Flow

```text
User adds source path
    |
    v
Web validates absolute /Users/... path
    |
    v
App metadata DB stores source root
    |
    v
Create or reuse per-source SQLite DB
    |
    v
Enumerate supported documents
    |
    v
Create one ingestion job per document
    |
    v
Worker polls next pending job
                    |
                    v
                Docling parses document (converter cached)
                (PDF pipeline now generates embedded picture images)
                    |
                    v
Structured extraction attempts:
    - sections
    - figures
    - tables
    |
    v
Normalize display text
with lowercase + lemmatization + stop-word removal
    |
    v
Write documents / content_units / term_postings
    |
    v
Compute embeddings for content units (model cached)
    |
    v
Rebuild per-source FAISS index
```

## Search Flow

```text
User submits query
    |
    v
Normalize query terms
    - tokenize
    - lowercase
    - lemmatize
    - remove stop words
    |
    v
Look up matching terms in term_postings
across all selected source DBs
    |
    v
Run semantic vector lookup in FAISS
across all selected source DBs
    |
    v
Build lexical candidate set
    |
    v
Score lexical candidates with BM25
    |
    v
Fuse lexical and semantic candidates
with reciprocal-rank-style fusion
    |
    v
Keep top fused candidates
    |
    v
Send candidates to reranker service
    |
    v
Cross-encoder scores query/passage pairs
    |
    v
Return final ranked results
    |
    v
User can optionally click ✨ on any result to summarize it
    |
    v
Click result to view document
    |
    v
/open/... -> /documents/...
    |
    v
Serve source document inline
with page fragment for PDFs when available
```

## Storage Layout

### App metadata DB

Purpose:

- global coordination
- source registration
- ingestion job tracking

Tables:

- `source_roots`
- `ingestion_jobs`
- `service_heartbeats`

### Per-source DB

Purpose:

- isolated index per whitelist source path

Tables:

- `documents`
- `content_units` – stores sections/figures/tables plus the `image_mime`/`image_data` columns used to show figure previews for matching results.
- `term_postings`
- `content_embeddings`

### Per-source FAISS index

Purpose:

- fast semantic nearest-neighbor lookup over `content_units`
- vector index keyed by `content_unit_id`
- kept alongside the per-source SQLite DB

## Runtime Location

Default local runtime state lives under:

- `~/.searchi/`

Docker Compose mounts that same `~/.searchi/` directory into the app services. Ollama runs natively on the host and uses the host's default `~/.ollama/` directory for model storage.

## Current Retrieval Semantics

### Normalization

Implemented:

- regex tokenization
- lowercase normalization
- lemmatization
- stop-word removal using the stopwords-iso English list (plus a handful of common contractions), which is now centralized in `app.services.stopwords`

Not implemented:

- stemming
- synonym expansion
- fuzzy lexical fallback

### Hybrid retrieval

Implemented:

- lexical retrieval from `term_postings`
- semantic retrieval from sentence embeddings
- current vector encoder:
  - `sentence-transformers/all-MiniLM-L6-v2`
- reciprocal-rank-style fusion before reranking

Current placement:

- vector retrieval is a candidate-generation stage
- it runs before reranking
- it complements lexical retrieval instead of replacing BM25

### Reranking

Implemented:

- real sentence-transformers cross-encoder service
- current default model:
  - `cross-encoder/ms-marco-MiniLM-L4-v2`

Behavior:

- reranker failures are surfaced explicitly
- no silent fallback to BM25 when reranking is enabled

### Summarization

Implemented:

- LLM-based per-result summarization service
- current default model:
  - `qwen2.5:0.5b-instruct` for per-result summaries and `gpt-oss` for cited answers (via Ollama, auto-downloaded on first startup)
- clicking the ✨ icon on any result card generates a single-sentence summary of that specific result
- input: individual result `display_text`
- output: single sentence summary

Behavior:

- summarizer failures are handled gracefully (summary is omitted)
- summaries appear inline below the result snippet
- summaries are generated on-demand (not pre-computed)

## Current Extraction Semantics

Implemented:

- Docling is required for ingestion
- Docling converter is cached per worker process (loaded once, reused across all documents)
- no silent file-text fallback
- extraction attempts separate `section`, `figure`, and `table` rows
- page numbers are taken from Docling provenance when available
- figure/table captions are used when available

Important caveat:

- the extraction layer is still being validated against real PDF outputs
- actual Docling structure quality remains the biggest area that still needs empirical verification

## Bounding Boxes

The installed Docling stack exposes spatial provenance fields including:

- `page_no`
- `bbox`
- `charspan`

and the bounding box object exposes:

- `l`
- `t`
- `r`
- `b`
- `coord_origin`

So bounding-box overlays are technically feasible enough to stay on the roadmap, but still need UI-side validation before they should be treated as committed functionality.

## UI / UX Notes

### Homepage

- Google-like centered search page
- `SearChi` branding
- Chi image background styling

### Sources view

- manual absolute path field
- native file picker
- native folder picker where browser support exists
- source clear/delete controls
- document and job status display

### Results view

- source filters
- result cards with:
  - highlighted snippets (click to expand/collapse full text with scrolling)
  - ✨ summarize icon in top-right corner for per-result AI summarization
  - inline summary display when icon is clicked
- explicit reranker/search errors when they occur

## Performance Optimizations

Model caching:

- Docling `DocumentConverter` is cached with `@lru_cache` (loaded once per worker process)
- Sentence transformer embedding model is cached with `@lru_cache` (loaded once per service)
- RapidOCR models are loaded once when the Docling converter initializes
- This means weights are loaded only at worker startup, not per-document

## Current Known Gaps

- exact open-at-text-location inside PDFs is not implemented
- OCR is not configured
- source picker behavior depends on browser support
- test coverage is still minimal
- Docling extraction quality still needs verification on your document set
- hybrid retrieval quality still needs empirical tuning:
  - FAISS rebuild strategy
  - fusion weights/rank constants
  - vector recall vs lexical recall balance
