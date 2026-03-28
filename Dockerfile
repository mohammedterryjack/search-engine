FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system -e .

RUN mkdir -p /app/data

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "search_engine.tui"]
