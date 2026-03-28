# Local Search Engine

Local, file-backed search engine built with Python, a per-whitelist SQLite page index, and a terminal UI.

## Design

- Filesystem is the source of truth.
- Each whitelist entry gets its own SQLite index under `data/indexes/`.
- SQLite stores only `documents(path, content_hash)` and `term_documents(term, content_hash, page_number)`.
- ripgrep is used only to enumerate candidate files during indexing.
- No document or page text is duplicated in the index. Page previews are derived live from the original files.

## Quick start

```bash
# TUI
docker compose run --rm app

# Plain text query
docker compose run --rm app python -m search_engine.tui --query president

# JSON query
docker compose run --rm app python -m search_engine.tui --query president --json
```

## Current file support

- `.txt`
- `.md`

## Notes

- Search results are page-level hits.
- If a text file contains `\f`, those explicit page breaks define the pages.
- If a text file contains no `\f`, the whole file is treated as page `1`.
- Whitelist entries and their indexes persist across sessions until explicitly cleared.
- Indexing runs in the background when you change the whitelist or submit a search.
- Submitting a search also triggers a background refresh so new or changed files get ingested without blocking the query.
- Docker mounts `/Users` read-only so whitelist paths can use normal host paths directly.
- The architecture diagram is in [architecture.md](/Users/mohammed/Code/search_engine/docs/architecture.md).
