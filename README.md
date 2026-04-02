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

## Known Issues & Troubleshooting

### Large PDF Memory Issues (OOM Crashes)

**Symptom**: Workers crash when processing large PDFs (>2MB), jobs marked as failed with "Worker crashed while processing (likely OOM)".

**Root Cause**: Docling's RapidOCR integration reloads model weights (~1.2GB) into memory for each document parse. This is a known Docling design limitation - models aren't reused across documents. The weights are cached on disk (not re-downloaded), but loaded fresh into memory each time.

**Current Workarounds**:
1. **Automatic handling**: Failed jobs can be manually retried from the Sources page if needed
2. **Worker scaling**: System runs 3 workers @ 4GB each - works well for small/medium PDFs (<500KB)
3. **For large PDFs**: Increase worker memory limit to 12GB and scale down to 1 worker:
   ```yaml
   # In docker-compose.yml
   worker:
     deploy:
       replicas: 1
       resources:
         limits:
           memory: 12G
   ```

**Memory Optimizations Applied**:
- `generate_parsed_pages=False` - Discards intermediate parse trees after extraction
- `images_scale=1.0` - Reduces image memory from default 2.0 (which quadruples area)
- `generate_page_images=False` - Skips page image generation

**Related Docling Issues**:
- [#773](https://github.com/docling-project/docling/issues/773) - Complex vector graphics in PDFs
- [#2540](https://github.com/docling-project/docling/issues/2540) - Memory optimization with `generate_parsed_pages`
- [#2607](https://github.com/docling-project/docling/issues/2607) - RapidOCR installation requirements

### System Library Requirements

If you encounter OCR-related errors in Docker, ensure these system libraries are installed in your Dockerfile:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
```

These are already included in the provided Dockerfile.
