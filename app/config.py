from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    app_db_path: Path
    source_db_dir: Path
    source_mount: Path
    host_source_root: Path
    reranker_url: str
    enable_reranker: bool
    poll_seconds: float


def get_settings() -> Settings:
    data_dir = Path(os.getenv("SEARCHY_DATA_DIR", "data")).resolve()
    app_db_path = Path(
        os.getenv("SEARCHY_APP_DB_PATH", str(data_dir / "app_data" / "searchy_app.sqlite3"))
    ).resolve()
    source_db_dir = Path(
        os.getenv("SEARCHY_SOURCE_DB_DIR", str(data_dir / "source_dbs"))
    ).resolve()
    source_mount = Path(os.getenv("SEARCHY_SOURCE_MOUNT", "/sources")).resolve()
    host_source_root = Path(os.getenv("SEARCHY_HOST_SOURCE_ROOT", "/tmp")).resolve()
    reranker_url = os.getenv("SEARCHY_RERANKER_URL", "http://localhost:8010")
    enable_reranker = os.getenv("SEARCHY_ENABLE_RERANKER", "1") == "1"
    poll_seconds = float(os.getenv("SEARCHY_POLL_SECONDS", "3"))

    return Settings(
        data_dir=data_dir,
        app_db_path=app_db_path,
        source_db_dir=source_db_dir,
        source_mount=source_mount,
        host_source_root=host_source_root,
        reranker_url=reranker_url,
        enable_reranker=enable_reranker,
        poll_seconds=poll_seconds,
    )
