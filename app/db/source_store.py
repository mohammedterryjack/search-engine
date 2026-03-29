from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def file_checksum(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SourceStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    file_checksum TEXT NOT NULL,
                    status TEXT NOT NULL,
                    page_count INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS content_units (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    unit_type TEXT NOT NULL,
                    page_number INTEGER,
                    section_name TEXT NOT NULL,
                    anchor_key TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    display_text TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id)
                );

                CREATE TABLE IF NOT EXISTS term_postings (
                    term TEXT NOT NULL,
                    content_unit_id INTEGER NOT NULL,
                    term_frequency INTEGER NOT NULL,
                    PRIMARY KEY(term, content_unit_id),
                    FOREIGN KEY(content_unit_id) REFERENCES content_units(id)
                );

                CREATE INDEX IF NOT EXISTS idx_documents_source_path
                ON documents(source_path);

                CREATE INDEX IF NOT EXISTS idx_content_units_document_id
                ON content_units(document_id);

                CREATE INDEX IF NOT EXISTS idx_term_postings_content_unit
                ON term_postings(content_unit_id);
                """
            )

    def has_document(self, document_path: Path) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM documents WHERE source_path = ?",
                (str(document_path.resolve()),),
            ).fetchone()
        return row is not None

    def list_documents(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC"
            ).fetchall()

    def upsert_document(
        self,
        document_path: Path,
        status: str,
        page_count: int | None,
        created_at: str,
        updated_at: str,
    ) -> int:
        checksum = file_checksum(document_path)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(
                    source_path, filename, file_checksum, status, page_count, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    filename = excluded.filename,
                    file_checksum = excluded.file_checksum,
                    status = excluded.status,
                    page_count = excluded.page_count,
                    updated_at = excluded.updated_at
                """,
                (
                    str(document_path.resolve()),
                    document_path.name,
                    checksum,
                    status,
                    page_count,
                    created_at,
                    updated_at,
                ),
            )
            row = conn.execute(
                "SELECT id FROM documents WHERE source_path = ?",
                (str(document_path.resolve()),),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to upsert document")
        return int(row["id"])

    def replace_content_units(self, document_id: int, units: list[dict[str, object]]) -> None:
        with self.connect() as conn:
            content_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM content_units WHERE document_id = ?",
                    (document_id,),
                ).fetchall()
            ]
            if content_ids:
                placeholders = ", ".join("?" for _ in content_ids)
                conn.execute(
                    f"DELETE FROM term_postings WHERE content_unit_id IN ({placeholders})",
                    content_ids,
                )
            conn.execute("DELETE FROM content_units WHERE document_id = ?", (document_id,))
            for unit in units:
                cursor = conn.execute(
                    """
                    INSERT INTO content_units(
                        document_id, unit_type, page_number, section_name, anchor_key,
                        text_content, caption, display_text, token_count, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        unit["unit_type"],
                        unit["page_number"],
                        unit["section_name"],
                        unit["anchor_key"],
                        unit["text_content"],
                        unit["caption"],
                        unit["display_text"],
                        unit["token_count"],
                        unit["created_at"],
                    ),
                )
                content_unit_id = int(cursor.lastrowid)
                for term, freq in unit["terms"].items():
                    conn.execute(
                        """
                        INSERT INTO term_postings(term, content_unit_id, term_frequency)
                        VALUES(?, ?, ?)
                        """,
                        (term, content_unit_id, freq),
                    )

    def delete_document(self, document_id: int) -> None:
        with self.connect() as conn:
            content_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM content_units WHERE document_id = ?",
                    (document_id,),
                ).fetchall()
            ]
            if content_ids:
                placeholders = ", ".join("?" for _ in content_ids)
                conn.execute(
                    f"DELETE FROM term_postings WHERE content_unit_id IN ({placeholders})",
                    content_ids,
                )
            conn.execute("DELETE FROM content_units WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM term_postings")
            conn.execute("DELETE FROM content_units")
            conn.execute("DELETE FROM documents")

    def content_unit_by_id(self, content_unit_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT cu.*, d.source_path AS document_path, d.filename
                FROM content_units cu
                JOIN documents d ON d.id = cu.document_id
                WHERE cu.id = ?
                """,
                (content_unit_id,),
            ).fetchone()
