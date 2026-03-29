# SirChi

SirChi is a local document search engine with:

- FastAPI web app
- Google-like search UI
- one SQLite database per whitelisted source path
- async ingestion worker
- multi-stage ranking pipeline

## Services

- `web`: FastAPI UI and API
- `worker`: background ingestion loop
- `reranker`: lightweight scoring service

## Local development

```bash
docker compose up --build
```

The app stores runtime data in `data/`.
