from __future__ import annotations

import asyncio
from typing import Callable

from .config import Settings
from .indexer import Indexer


class SyncService:
    def __init__(self, settings: Settings, indexer: Indexer) -> None:
        self.settings = settings
        self.indexer = indexer
        self._scan_task: asyncio.Task[None] | None = None
        self.on_state_change: Callable[[], None] | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        if self.settings.sync.scan_on_start:
            self.trigger_refresh()

    async def stop(self) -> None:
        if self._scan_task is not None:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

    @property
    def is_indexing(self) -> bool:
        return self._scan_task is not None and not self._scan_task.done()

    def trigger_refresh(self) -> None:
        if self._scan_task is None or self._scan_task.done():
            self.last_error = None
            self._scan_task = asyncio.create_task(asyncio.to_thread(self.indexer.initial_scan))
            self._notify_state_change()
            self._scan_task.add_done_callback(self._on_scan_done)

    def reload_roots(self, settings: Settings) -> None:
        self.settings = settings
        self.indexer.settings = settings

    def _notify_state_change(self) -> None:
        if self.on_state_change is not None:
            self.on_state_change()

    def _on_scan_done(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception as exc:
            self.last_error = str(exc)
        self._notify_state_change()
