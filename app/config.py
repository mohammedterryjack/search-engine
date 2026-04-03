from __future__ import annotations

import os
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path


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


def default_data_dir() -> Path:
    return (Path.home() / ".searchi").resolve()



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.getenv("SEARCHY_DATA_DIR", str(default_data_dir()))).resolve()
    app_db_path = Path(
        os.getenv("SEARCHY_APP_DB_PATH", str(data_dir / "app_data" / "searchi_app.sqlite3"))
    ).resolve()
    source_db_dir = Path(
        os.getenv("SEARCHY_SOURCE_DB_DIR", str(data_dir / "source_dbs"))
    ).resolve()
    allowed_source_root = Path(os.getenv("SEARCHY_ALLOWED_SOURCE_ROOT", "/Users")).resolve()
    vector_model_name = os.getenv(
        "SEARCHY_VECTOR_MODEL",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    enable_vector_retrieval = os.getenv("SEARCHY_ENABLE_VECTOR_RETRIEVAL", "1") == "1"
    vector_min_score_default = float(os.getenv("SEARCHY_VECTOR_MIN_SCORE_DEFAULT", "0.2"))
    reranker_url = os.getenv("SEARCHY_RERANKER_URL", "http://localhost:8010")
    reranker_timeout = float(os.getenv("SEARCHY_RERANKER_TIMEOUT", "15"))
    status_token = os.getenv("SEARCHY_STATUS_TOKEN", "searchi-local-status")
    enable_reranker = os.getenv("SEARCHY_ENABLE_RERANKER", "1") == "1"
    poll_seconds = float(os.getenv("SEARCHY_POLL_SECONDS", "3"))
    enable_summarizer = os.getenv("SEARCHY_ENABLE_SUMMARIZER", "1") == "1"
    summarizer_url = os.getenv("SEARCHY_SUMMARIZER_URL", "http://localhost:11434")
    summarizer_model = os.getenv("SEARCHY_SUMMARIZER_MODEL", "Falconsai/text_summarization")
    summarizer_timeout = float(os.getenv("SEARCHY_SUMMARIZER_TIMEOUT", "180.0"))

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
    )
