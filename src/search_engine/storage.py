from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import DocumentRecord


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  path TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS term_documents (
  term TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  PRIMARY KEY(term, content_hash, page_number)
);

CREATE INDEX IF NOT EXISTS idx_term_documents_hash ON term_documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_term_documents_page ON term_documents(content_hash, page_number);
"""


class MetadataStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            legacy_tables = {"files", "pages", "terms", "postings", "search_roots"}
            if tables & legacy_tables:
                for table in legacy_tables:
                    connection.execute(f"DROP TABLE IF EXISTS {table}")
            if self._table_columns(connection, "documents") not in (set(), {"path", "content_hash"}):
                connection.execute("DROP TABLE IF EXISTS documents")
            if self._table_columns(connection, "term_documents") not in (set(), {"term", "content_hash", "page_number"}):
                connection.execute("DROP TABLE IF EXISTS term_documents")
            connection.executescript(SCHEMA)

    def get(self, path: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM documents WHERE path = ?", (path,)).fetchone()

    def list_paths(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT path FROM documents").fetchall()
        return {row["path"] for row in rows}

    def upsert_document(self, record: DocumentRecord, page_terms: dict[int, set[str]]) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT content_hash FROM documents WHERE path = ?",
                (str(record.path),),
            ).fetchone()
            old_hash = existing["content_hash"] if existing else None

            connection.execute(
                """
                INSERT INTO documents(path, content_hash)
                VALUES(?, ?)
                ON CONFLICT(path) DO UPDATE SET
                  content_hash = excluded.content_hash
                """,
                (
                    str(record.path),
                    record.content_hash,
                ),
            )

            if old_hash != record.content_hash:
                self._delete_term_links_if_orphaned(connection, old_hash)
                connection.execute("DELETE FROM term_documents WHERE content_hash = ?", (record.content_hash,))

            if page_terms:
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO term_documents(term, content_hash, page_number)
                    VALUES(?, ?, ?)
                    """,
                    [
                        (term, record.content_hash, page_number)
                        for page_number, terms in sorted(page_terms.items())
                        for term in sorted(terms)
                    ],
                )

    def search_documents(self, terms: list[str]) -> list[sqlite3.Row]:
        if not terms:
            return []
        placeholders = ", ".join("?" for _ in terms)
        with self._connect() as connection:
            return connection.execute(
                f"""
                SELECT
                  td.term,
                  td.content_hash,
                  td.page_number,
                  d.path
                FROM term_documents td
                JOIN documents d ON d.content_hash = td.content_hash
                WHERE td.term IN ({placeholders})
                """,
                tuple(terms),
            ).fetchall()

    def page_terms(self, page_keys: list[tuple[str, int]]) -> list[sqlite3.Row]:
        if not page_keys:
            return []
        conditions = " OR ".join("(content_hash = ? AND page_number = ?)" for _ in page_keys)
        params = [value for page_key in page_keys for value in page_key]
        with self._connect() as connection:
            return connection.execute(
                f"""
                SELECT term, content_hash, page_number
                FROM term_documents
                WHERE {conditions}
                """,
                tuple(params),
            ).fetchall()

    def document_frequency(self, term: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM term_documents WHERE term = ?",
                (term,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def page_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                  SELECT content_hash, page_number
                  FROM term_documents
                  GROUP BY content_hash, page_number
                )
                """
            ).fetchone()
        return int(row["count"]) if row else 0

    def total_file_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()
        return int(row["count"]) if row else 0

    def unique_hash_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(DISTINCT content_hash) AS count FROM documents").fetchone()
        return int(row["count"]) if row else 0

    def term_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(DISTINCT term) AS count FROM term_documents").fetchone()
        return int(row["count"]) if row else 0

    def list_terms(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT DISTINCT term FROM term_documents").fetchall()
        return {str(row["term"]) for row in rows}

    def term_link_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM term_documents").fetchone()
        return int(row["count"]) if row else 0

    def database_size_bytes(self) -> int:
        path = Path(self.db_path)
        if not path.exists():
            return 0
        return path.stat().st_size

    def table_stats(self) -> list[dict[str, int | str | None]]:
        tables = ["documents", "term_documents"]
        stats: list[dict[str, int | str | None]] = []
        with self._connect() as connection:
            for table in tables:
                row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                count = int(row["count"]) if row else 0
                size_bytes: int | None = None
                try:
                    size_row = connection.execute(
                        "SELECT SUM(pgsize) AS size_bytes FROM dbstat WHERE name = ?",
                        (table,),
                    ).fetchone()
                    if size_row and size_row["size_bytes"] is not None:
                        size_bytes = int(size_row["size_bytes"])
                except sqlite3.DatabaseError:
                    size_bytes = None
                stats.append({"table": table, "rows": count, "size_bytes": size_bytes})
        return stats

    def delete(self, path: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM documents WHERE path = ?",
                (path,),
            ).fetchone()
            content_hash = row["content_hash"] if row else None
            connection.execute("DELETE FROM documents WHERE path = ?", (path,))
            self._delete_term_links_if_orphaned(connection, content_hash)

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM term_documents")
            connection.commit()
            connection.execute("VACUUM")

    def _delete_term_links_if_orphaned(self, connection: sqlite3.Connection, content_hash: str | None) -> None:
        if not content_hash:
            return
        row = connection.execute(
            "SELECT 1 FROM documents WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        ).fetchone()
        if row is None:
            connection.execute("DELETE FROM term_documents WHERE content_hash = ?", (content_hash,))

    @staticmethod
    def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row["name"]) for row in rows}
