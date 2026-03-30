# Manual Testing

This file is the user-facing checklist for validating `SearChi` manually on a real local corpus.

Use [manual_testing_feedback.md](/Users/mohammed/Code/search_engine/manual_testing_feedback.md) to note issues as you find them.

## Reingest Rules

Reingest is needed after changes to:

- tokenization or lemmatization
- Docling extraction logic
- noisy-text cleanup logic
- embedding model or vector indexing logic

Reingest is not needed after changes to:

- UI or styling
- routes and templates
- status/visibility pages
- reranker-only display changes

## Current Test Pass

### 1. Source Management

- add one representative PDF-heavy source
- add a single file source as well as a folder source if relevant
- confirm the source appears in `Sources`
- confirm indexed document counts look plausible
- confirm failed jobs, if any, surface clearly
- confirm retry controls behave correctly

### 2. Ingestion Quality

- check that sections are appearing as results
- check that figures are appearing as results
- check that tables are appearing as results
- check that page numbers look correct
- check that captions/titles from Docling look reasonable
- note any obvious garbage extraction, merged words, or broken spacing

### 3. Search Behavior

- run a lexical query with obvious exact matches
- run a query that should match a figure caption
- run a query that should match a table
- run a more semantic/paraphrased query
- confirm the source filter works
- confirm the section/figure/table filter works
- confirm the semantic strictness slider changes the result set sensibly

### 4. Result Quality

- confirm snippets look reasonable
- confirm highlights align with the matched text
- confirm result titles feel sensible for sections/figures/tables
- note any obviously irrelevant vector hits
- note if BM25-style lexical hits seem better or worse than expected

### 5. Open Document Behavior

- open several PDF results
- confirm they open inside the app
- confirm page-level jumps are correct when page numbers exist
- note any cases where the wrong page opens

### 6. Status and Sources Views

- confirm the Status page is understandable
- confirm reranker status looks correct
- confirm source/job stats look plausible
- confirm indexing activity is visible while jobs are running

### 7. Native Picker

- test double-clicking the path field
- test file picking
- test folder picking
- note whether your browser exposes usable absolute paths
- if not, confirm manual absolute path entry remains acceptable

## What To Record In Feedback

When something looks wrong, write down:

- the page you were on
- the query or source path used
- what you expected
- what actually happened
- whether reingest had happened before the test
