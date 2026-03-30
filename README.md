# SearChi

SearChi is a local document search engine with:

- FastAPI web app
- Google-like search UI
- one SQLite database per whitelisted source path
- async ingestion worker
- multi-stage ranking pipeline

## Services

- `web`: FastAPI UI and API
- `worker`: background ingestion loop
- `reranker`: cross-encoder reranking service

## Local development

```bash
make rebuild
```

With the default local configuration, runtime data lives under `~/.searchi/`.

The Docker Compose setup still uses the repo-local `./data/` directory explicitly for development convenience.

## CLI

Text output:

```bash
uv run searchi "chaos attractor"
```

JSON output:

```bash
uv run searchi "chaos attractor" --json
```
