# Architecture

This design keeps the persisted state minimal. The database stores only document metadata, content hashes, and `term -> content_hash` links. It does not store page text, snippets, page-level postings, or saved root selections.

```text
                +---------------------------+
                | TUI                       |
                | Search | Roots | Stats    |
                +---------------------------+
                     |        |        |
                     |        |        +----------------------+
                     |        |                               |
                     |        +--> add/remove roots -----------+
                     |                                        |
                     v                                        v
            +------------------+                    +----------------------+
            | Query Parser     |                    | SQLite Local State   |
            | tokenize query   |                    | documents            |
            +------------------+                    | term_documents       |
                     |                              |                      |
                     v                              +----------------------+
            +------------------+
            | Term shortlist   |
            | term -> hashes   |
            +------------------+
                     |
                     v
            +------------------+
            | Candidate docs   |
            | path + hash       |
            +------------------+
                     |
                     v
            +------------------+
            | ripgrep          |
            | exact hit lines  |
            +------------------+
                     |
                     v
            +------------------+
            | Live page build  |
            | page # + snippet |
            +------------------+
                     |
                     v
            +------------------+
            | Preview / result |
            | from source file |
            +------------------+


Configured Roots
    |
    v
+------------------+
| ripgrep --files  |
| candidate scan   |
+------------------+
    |
    v
+------------------+      changed files only      +----------------------+
| Read text file   | ---------------------------> | SQLite documents     |
| hash + tokenize  |                              | path + content_hash  |
+------------------+                              +----------------------+
    |
    v
+------------------+      unique terms only       +----------------------+
| Stop-word filter | ---------------------------> | SQLite term index    |
| normalize terms  |                              | term_documents       |
+------------------+                              +----------------------+
```

## Stored Data

- `documents`
  - file path, root/display metadata, cheap file metadata, content hash
- `term_documents`
  - unique indexed terms linked to a content hash
## Query Flow

1. Tokenize the query and drop stop words.
2. Use the SQLite term index to shortlist candidate documents.
3. Run `ripgrep` only on those shortlisted files to find exact hit lines.
4. Build a synthetic page around each hit line from the original file.
5. Render the result list and preview from the source file.

## Consequences

- The DB is smaller than the old page-level design because it no longer stores pages, positions, or postings.
- Startup and search remain responsive because indexing runs in the background.
- Submitting a search triggers a background refresh, so the local index improves without blocking the current query.
- Roots are session-only and are not stored in the DB.
- Search results may miss a brand-new file until the background refresh ingests it, which is the tradeoff for keeping queries non-blocking.
- The `Stats` tab reports DB size, table sizes, indexed file counts, unique hashes, and term-link counts from the local SQLite store.
