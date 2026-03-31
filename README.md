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

The Docker Compose setup also points at the host `~/.searchi/` directory via a bind mount (so nothing is written to `./data/` anymore).

### Refreshing the term index after stop-word changes

The stop-word list now includes a much larger set of tokens, so you should rerun ingestion or prune the existing index before relying on the new behavior. Use the helper script before restarting the app:

```bash
python scripts/prune_stopwords.py
```

That deletes all postings whose term appears in the expanded stop-word set; new ingests will naturally skip them going forward.

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
