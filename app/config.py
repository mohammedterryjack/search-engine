from __future__ import annotations

import os
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    app_db_path: Path
    source_db_dir: Path
    allowed_source_root: Path
    vector_model_name: str
    enable_vector_retrieval: bool
    vector_min_score_default: float
    reranker_url: str
    reranker_timeout: float
    status_token: str
    enable_reranker: bool
    poll_seconds: float
    enable_summarizer: bool
    summarizer_url: str
    summarizer_model: str
    summarizer_timeout: float
    ai_source_limit: int


def default_data_dir() -> Path:
    return (Path.home() / ".searchi").resolve()



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(require_env("SEARCHY_DATA_DIR")).resolve()
    app_db_path = Path(
        require_env("SEARCHY_APP_DB_PATH")
    ).resolve()
    source_db_dir = Path(
        require_env("SEARCHY_SOURCE_DB_DIR")
    ).resolve()
    allowed_source_root = Path(require_env("SEARCHY_ALLOWED_SOURCE_ROOT")).resolve()
    vector_model_name = require_env("SEARCHY_VECTOR_MODEL")
    enable_vector_retrieval = require_env("SEARCHY_ENABLE_VECTOR_RETRIEVAL") == "1"
    vector_min_score_default = float(require_env("SEARCHY_VECTOR_MIN_SCORE_DEFAULT"))
    reranker_url = require_env("SEARCHY_RERANKER_URL")
    reranker_timeout = float(require_env("SEARCHY_RERANKER_TIMEOUT"))
    status_token = require_env("SEARCHY_STATUS_TOKEN")
    enable_reranker = require_env("SEARCHY_ENABLE_RERANKER") == "1"
    poll_seconds = float(require_env("SEARCHY_POLL_SECONDS"))
    enable_summarizer = require_env("SEARCHY_ENABLE_SUMMARIZER") == "1"
    summarizer_url = require_env("SEARCHY_SUMMARIZER_URL")
    summarizer_model = require_env("SEARCHY_SUMMARY_MODEL")
    summarizer_timeout = float(require_env("SEARCHY_SUMMARIZER_TIMEOUT"))
    ai_source_limit = int(require_env("SEARCHY_AI_SOURCE_LIMIT"))

    return Settings(
        data_dir=data_dir,
        app_db_path=app_db_path,
        source_db_dir=source_db_dir,
        allowed_source_root=allowed_source_root,
        vector_model_name=vector_model_name,
        enable_vector_retrieval=enable_vector_retrieval,
        vector_min_score_default=vector_min_score_default,
        reranker_url=reranker_url,
        reranker_timeout=reranker_timeout,
        status_token=status_token,
        enable_reranker=enable_reranker,
        poll_seconds=poll_seconds,
        enable_summarizer=enable_summarizer,
        summarizer_url=summarizer_url,
        summarizer_model=summarizer_model,
        summarizer_timeout=summarizer_timeout,
        ai_source_limit=ai_source_limit,
    )
