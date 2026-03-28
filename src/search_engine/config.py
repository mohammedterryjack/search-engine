from __future__ import annotations

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    title: str = "Local Search Engine"
    database_path: str = "/app/data/index_state.db"
    snippet_length: int = 240


class SyncConfig(BaseModel):
    scan_on_start: bool = True


class RootConfig(BaseModel):
    name: str
    path: str
    include_globs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    app: AppConfig
    sync: SyncConfig
    roots: list[RootConfig] = Field(default_factory=list)


def load_settings() -> Settings:
    return Settings(
        app=AppConfig(),
        sync=SyncConfig(),
        roots=[],
    )
