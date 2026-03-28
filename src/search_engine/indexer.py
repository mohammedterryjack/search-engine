from __future__ import annotations

import fnmatch
import hashlib
import logging
import subprocess
from pathlib import Path

from .config import RootConfig, Settings
from .index_registry import IndexRegistry
from .models import DocumentRecord
from .paging import split_pages_in_text
from .search_backend import tokenize_terms

logger = logging.getLogger(__name__)


class Indexer:
    def __init__(self, settings: Settings, registry: IndexRegistry) -> None:
        self.settings = settings
        self.registry = registry

    def initial_scan(self) -> None:
        if not self.settings.roots:
            return
        for root in self.settings.roots:
            for path in self._discover_files(root):
                self.index_file(path, root)

    def index_file(self, path: Path, root: RootConfig | None = None) -> None:
        root = root or self._resolve_root(path)
        if root is None or not path.exists() or not path.is_file():
            return

        store = self.registry.get_store(root)
        record = store.get(str(path))

        try:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
            normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
            content_hash = hashlib.sha1(raw_text.encode("utf-8", errors="ignore")).hexdigest()
        except OSError as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return

        if record and record["content_hash"] == content_hash:
            store.upsert_document(
                DocumentRecord(
                    path=path,
                    content_hash=content_hash,
                ),
                {},
            )
            return

        page_terms = {
            page_number: set(tokenize_terms(page_text))
            for page_number, _, _, page_text in split_pages_in_text(normalized_text, self.settings.paging)
        }
        store.upsert_document(
            DocumentRecord(
                path=path,
                content_hash=content_hash,
            ),
            page_terms,
        )

    def remove_file(self, path: Path) -> None:
        root = self._resolve_root(path)
        if root is None:
            return
        self.registry.get_store(root).delete(str(path))

    def _resolve_root(self, path: Path) -> RootConfig | None:
        for root in self.settings.roots:
            base = Path(root.path)
            try:
                path.relative_to(base)
                if _matches(path, root, base):
                    return root
            except ValueError:
                continue
        return None

    def _discover_files(self, root: RootConfig) -> list[Path]:
        base_path = Path(root.path)
        if not base_path.exists():
            logger.warning("Configured root does not exist: %s", base_path)
            return []

        command = ["rg", "--files", str(base_path)]
        for pattern in root.include_globs:
            command.extend(["-g", pattern])
        for pattern in root.exclude_globs:
            command.extend(["-g", f"!{pattern}"])

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            logger.warning("ripgrep not available, falling back to Python discovery")
            return [path for path in base_path.rglob("*") if path.is_file() and _matches(path, root, base_path)]

        if result.returncode not in {0, 1}:
            logger.warning("ripgrep discovery failed for %s: %s", base_path, result.stderr.strip())
            return [path for path in base_path.rglob("*") if path.is_file() and _matches(path, root, base_path)]

        return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _matches(path: Path, root: RootConfig, base_path: Path) -> bool:
    relative_path = path.relative_to(base_path).as_posix()
    candidates = {relative_path, f"**/{relative_path}"}
    if root.include_globs and not any(
        any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates) for pattern in root.include_globs
    ):
        return False
    if root.exclude_globs and any(
        any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates) for pattern in root.exclude_globs
    ):
        return False
    return True
