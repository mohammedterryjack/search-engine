from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    title: str = "Local Search Engine"
    database_path: str = "/app/data/index_state.db"
    snippet_length: int = 240


class SyncConfig(BaseModel):
    scan_on_start: bool = True
    reconcile_interval_seconds: int = 300
    debounce_seconds: float = 1.0


class PagingConfig(BaseModel):
    text_page_chars: int = 1800
    min_page_chars: int = 900


class RootConfig(BaseModel):
    name: str
    path: str
    include_globs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    app: AppConfig
    sync: SyncConfig
    paging: PagingConfig
    roots: list[RootConfig] = Field(default_factory=list)


def load_settings() -> Settings:
    return Settings(
        app=AppConfig(),
        sync=SyncConfig(),
        paging=PagingConfig(),
        roots=[],
    )


def flatten_for_template(settings: Settings) -> dict[str, Any]:
    return {
        "title": settings.app.title,
        "roots": settings.roots,
    }
