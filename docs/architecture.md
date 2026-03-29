# Architecture

This is the target architecture for `Searchy`, the new web-based local search engine.

## System Diagram

```text
                                +----------------------+
                                | Browser              |
                                | Searchy UI           |
                                | Google-like pages    |
                                +----------+-----------+
                                           |
                                           v
                                +----------------------+
                                | FastAPI Web App      |
                                | HTML + API + /open   |
                                +----+------------+----+
                                     |            |
                   add source path   |            | search query
                                     |            |
                                     v            v
                         +------------------+   +----------------------+
                         | Job Registry     |   | Query Service        |
                         | app metadata DB  |   | tokenize query       |
                         | source_roots     |   | gather candidates    |
                         | ingestion_jobs   |   | BM25 top 100         |
                         +--------+---------+   | rerank results       |
                                  |             +----+-----------------+
                                  |                  |
                                  v                  v
                         +------------------+   +----------------------+
                         | Async Worker     |   | Reranker Service     |
                         | Docling ingest   |   | cross-encoder        |
                         | parse documents  |   | local model          |
                         +--------+---------+   +----------------------+
                                  |
                                  v
                      +---------------------------+
                      | Per-Source SQLite DB      |
                      | one DB per whitelist path |
                      |                           |
                      | documents                 |
                      | content_units             |
                      | term_postings             |
                      +------------+--------------+
                                   |
                                   v
                      +---------------------------+
                      | Local Filesystem Sources  |
                      | file or directory paths   |
                      | all Docling-supported docs|
                      +---------------------------+
```

## Ingestion Flow

```text
User adds whitelist path
    |
    v
FastAPI validates file/directory path
    |
    v
App metadata DB stores source root
    |
    v
Create per-source SQLite DB if missing
    |
    v
Enumerate supported documents under source
    |
    v
Create one ingestion job per new document
    |
    v
Worker picks next pending job
    |
    v
Docling parses sections / figures / tables
    |
    v
Normalize into content rows
    |
    v
Tokenize display text
    |
    v
Write documents / content_units / term_postings
```

## Search Flow

```text
User submits query
    |
    v
Normalize and tokenize query
    |
    v
Look up matching terms in term_postings
across all selected source DBs
    |
    v
Build candidate content_unit set
    |
    v
Score with BM25 in Python
    |
    v
Keep top 100
    |
    v
Send top 100 to cross-encoder reranker
    |
    v
Render final ranked results
with snippets and term highlights
    |
    v
Click result -> /open/{content_unit_id}
    |
    v
Open source doc at page when possible
```

## Storage Layout

### App metadata DB

Small central SQLite database used for global coordination:

- `source_roots`
- `ingestion_jobs`
- optional global settings

### Per-source DB

One SQLite database per whitelist source path:

- `documents`
- `content_units`
- `term_postings`

This matches the product rule that each source path owns its own inverted index store.

## Key Behavior

- Source paths are explicit user-managed whitelist entries.
- Ingestion happens automatically when a source is added.
- Documents are treated as immutable after ingestion.
- No automatic rescans or change detection.
- User can remove an individual document from a source DB.
- User can clear a full source DB from a management view.
- Search spans all sources by default, with source filtering.
- Each Docling section, figure, and table is stored as a separate row.
- Open-at-location is best-effort; page-level PDF opening is the reliable baseline.
