from __future__ import annotations

from .config import Settings, load_settings
from .indexer import Indexer
from .index_registry import IndexRegistry
from .search_backend import SearchBackend
from .sync import SyncService


def build_runtime() -> tuple[Settings, IndexRegistry, SearchBackend, Indexer, SyncService]:
    settings = load_settings()
    registry = IndexRegistry(settings.app.database_path)
    settings = settings.model_copy(update={"roots": registry.load_active_roots()})
    backend = SearchBackend(
        registry,
        paging=settings.paging,
        roots=settings.roots,
        snippet_length=settings.app.snippet_length,
    )
    indexer = Indexer(settings, registry)
    sync_service = SyncService(settings, indexer)
    return settings, registry, backend, indexer, sync_service
