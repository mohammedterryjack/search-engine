# SearChi

SearChi is a local document search engine with:

- FastAPI web app
- Google-like search UI
- one SQLite database per whitelisted source path
- async ingestion worker
- multi-stage ranking pipeline
- per-result AI summarization (✨ button on each result)

## Services

- `web`: FastAPI UI and API
- `worker`: background ingestion loop
- `reranker`: cross-encoder reranking service

## Local development

```bash
make rebuild
```

With the default local configuration, runtime data lives under `~/.searchi/`.

The Docker Compose setup also points at the host `~/.searchi/` directory via a bind mount (so nothing is written to `./data/` anymore).

**Note:** On first startup, the summariser service will automatically download the `qwen2.5:0.5b-instruct` model (~300MB). This may take a minute or two depending on your connection speed.

## HTTP API

You can hit the same `/search` endpoint that the UI uses directly with `curl`:

```bash
curl -s -G http://localhost:18000/search --data-urlencode "q=chaos attractor"
```

Use `unit_type` or `vector_min_score` as additional query parameters:

```bash
curl -s -G http://localhost:18000/search \
  --data-urlencode "q=chaos attractor" \
  --data-urlencode "unit_type=figure" \
  --data-urlencode "vector_min_score=0.3"
```

Add `| jq` if you want the JSON response formatted.
