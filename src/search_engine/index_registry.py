from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import RootConfig
from .storage import MetadataStore


class IndexRegistry:
    def __init__(self, base_path: str) -> None:
        base = Path(base_path)
        self.base_dir = base.parent if base.suffix else base
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.base_dir / "whitelist_registry.json"
        self.index_dir = self.base_dir / "indexes"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._stores: dict[str, MetadataStore] = {}

    def load_active_roots(self) -> list[RootConfig]:
        data = self._load_registry()
        active_keys = data.get("active_keys", [])
        entries = data.get("entries", {})
        roots: list[RootConfig] = []
        for key in active_keys:
            entry = entries.get(key)
            if not entry:
                continue
            roots.append(
                RootConfig(
                    name=str(entry["name"]),
                    path=str(entry["path"]),
                    include_globs=list(entry.get("include_globs", [])),
                    exclude_globs=list(entry.get("exclude_globs", [])),
                )
            )
        return roots

    def set_active_roots(self, roots: list[RootConfig]) -> None:
        data = self._load_registry()
        entries = data.setdefault("entries", {})
        active_keys: list[str] = []
        for root in roots:
            key = self._root_key(root)
            db_path = str(self.index_dir / f"{key}.db")
            entries[key] = {
                "name": root.name,
                "path": root.path,
                "include_globs": list(root.include_globs),
                "exclude_globs": list(root.exclude_globs),
                "db_path": db_path,
            }
            active_keys.append(key)
        data["active_keys"] = active_keys
        self._save_registry(data)

    def get_store(self, root: RootConfig) -> MetadataStore:
        key = self._root_key(root)
        data = self._load_registry()
        entries = data.setdefault("entries", {})
        entry = entries.get(key)
        if entry is None:
            db_path = str(self.index_dir / f"{key}.db")
            entry = {
                "name": root.name,
                "path": root.path,
                "include_globs": list(root.include_globs),
                "exclude_globs": list(root.exclude_globs),
                "db_path": db_path,
            }
            entries[key] = entry
            self._save_registry(data)
        db_path = str(entry["db_path"])
        store = self._stores.get(db_path)
        if store is None:
            store = MetadataStore(db_path)
            self._stores[db_path] = store
        return store

    def stores_for_roots(self, roots: list[RootConfig]) -> list[MetadataStore]:
        return [self.get_store(root) for root in roots]

    def search_documents(self, terms: list[str], roots: list[RootConfig]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for store in self.stores_for_roots(roots):
            rows.extend(dict(row) for row in store.search_documents(terms))
        return rows

    def document_frequency(self, term: str, roots: list[RootConfig]) -> int:
        return sum(store.document_frequency(term) for store in self.stores_for_roots(roots))

    def total_file_count(self, roots: list[RootConfig]) -> int:
        return sum(store.total_file_count() for store in self.stores_for_roots(roots))

    def unique_hash_count(self, roots: list[RootConfig]) -> int:
        return sum(store.unique_hash_count() for store in self.stores_for_roots(roots))

    def page_count(self, roots: list[RootConfig]) -> int:
        return sum(store.page_count() for store in self.stores_for_roots(roots))

    def term_count(self, roots: list[RootConfig]) -> int:
        seen_terms: set[str] = set()
        for store in self.stores_for_roots(roots):
            seen_terms.update(store.list_terms())
        return len(seen_terms)

    def term_link_count(self, roots: list[RootConfig]) -> int:
        return sum(store.term_link_count() for store in self.stores_for_roots(roots))

    def database_size_bytes(self, roots: list[RootConfig]) -> int:
        return sum(store.database_size_bytes() for store in self.stores_for_roots(roots))

    def table_stats(self, roots: list[RootConfig]) -> list[dict[str, int | str | None]]:
        combined: dict[str, dict[str, int | str | None]] = {}
        for store in self.stores_for_roots(roots):
            for item in store.table_stats():
                current = combined.setdefault(
                    str(item["table"]),
                    {"table": item["table"], "rows": 0, "size_bytes": 0},
                )
                current["rows"] = int(current["rows"] or 0) + int(item["rows"])
                if item["size_bytes"] is None:
                    current["size_bytes"] = None
                elif current["size_bytes"] is not None:
                    current["size_bytes"] = int(current["size_bytes"] or 0) + int(item["size_bytes"])
        return list(combined.values())

    def clear(self, roots: list[RootConfig]) -> None:
        for store in self.stores_for_roots(roots):
            store.clear()

    @staticmethod
    def _normalized_root(root: RootConfig) -> dict[str, object]:
        return {
            "path": str(Path(root.path).expanduser().resolve(strict=False)),
            "include_globs": sorted(root.include_globs),
            "exclude_globs": sorted(root.exclude_globs),
        }

    def _root_key(self, root: RootConfig) -> str:
        payload = json.dumps(self._normalized_root(root), sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _load_registry(self) -> dict[str, object]:
        if not self.registry_path.exists():
            return {"active_keys": [], "entries": {}}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _save_registry(self, data: dict[str, object]) -> None:
        self.registry_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
