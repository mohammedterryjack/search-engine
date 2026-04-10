# Models Used in SearChi

This document describes the current model setup in the repo.

## Current Runtime

Shared model settings are defined in [`/.env`](/Users/mohammed/Code/search_engine/.env) and wired through [`/docker-compose.yml`](/Users/mohammed/Code/search_engine/docker-compose.yml).

- Summary model: `qwen2.5:0.5b-instruct`
- AI answer model: `gpt-oss`
- Ollama context size: `32768`

The summariser and AI answer path are currently text-only. Search results may still contain figure images for UI display, but image payloads are not forwarded to the Ollama model.

## Document Parsing

Service: `parser`

- Primary stack: Docling
- OCR stack: RapidOCR / PP-OCRv4
- Purpose: extract text, figures, tables, and structure from indexed documents
- Runtime note: parser is configured for 1 replica in [`/docker-compose.yml`](/Users/mohammed/Code/search_engine/docker-compose.yml)

## Summaries And AI Answers

Service: `summariser`

- Runtime: native host Ollama, reached from Docker via `host.docker.internal`
- Summary model: `qwen2.5:0.5b-instruct`
- AI answer model: `gpt-oss`
- Summary behavior: short, 2-3 sentence summaries for individual results
- AI answer behavior: fuller cited answers grounded in retrieved search sources

Model artifacts are stored on the host in:

```text
~/.ollama
```

## Result Reranking

Service: `reranker`

- Model: `cross-encoder/ms-marco-MiniLM-L4-v2`
- Purpose: rerank top search hits against the user query
- Batch size: `16`

Hugging Face cache path:

```text
~/.searchi/model_cache/huggingface
```

## Semantic Search

Services: `web` and `parser`

- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- Vector dimensions: `384`
- Backend: FAISS on CPU
- Purpose: semantic retrieval over indexed content units

## Updating Models

Change the model settings in [`/.env`](/Users/mohammed/Code/search_engine/.env), ensure the models exist in your host Ollama instance, then recreate the affected services.

Typical restart command:

```bash
docker compose up -d --force-recreate summariser web parser
```

If you change reranker settings, recreate `reranker` too.
