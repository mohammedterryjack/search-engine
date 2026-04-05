from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.services.vector_store import faiss_path_for_db

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
                    token_count INTEGER NOT NULL,
                    image_mime TEXT,
                    image_data TEXT,
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

                CREATE TABLE IF NOT EXISTS content_embeddings (
                    content_unit_id INTEGER PRIMARY KEY,
                    embedding_model TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
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
            self._ensure_column(conn, "content_units", "image_mime", "TEXT")
            self._ensure_column(conn, "content_units", "image_data", "TEXT")


    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing_columns = {row["name"] for row in rows}
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

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
                conn.execute(
                    f"DELETE FROM content_embeddings WHERE content_unit_id IN ({placeholders})",
                    content_ids,
                )
            conn.execute("DELETE FROM content_units WHERE document_id = ?", (document_id,))
            for unit in units:
                image_mime = unit.get("image_mime")
                image_data = unit.get("image_data")
                cursor = conn.execute(
                    """
                    INSERT INTO content_units(
                        document_id, unit_type, page_number, section_name, anchor_key,
                        text_content, caption, token_count, created_at,
                        image_mime, image_data
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        unit["unit_type"],
                        unit["page_number"],
                        unit["section_name"],
                        unit["anchor_key"],
                        unit["text_content"],
                        unit["caption"],
                        unit["token_count"],
                        unit["created_at"],
                        image_mime,
                        image_data,
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
                conn.execute(
                    """
                    INSERT OR REPLACE INTO content_embeddings(content_unit_id, embedding_model, updated_at)
                    VALUES(?, ?, ?)
                    """,
                    (
                        content_unit_id,
                        unit["embedding_model"],
                        unit["created_at"],
                    ),
                )

    def document_content_unit_ids(self, document_id: int) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM content_units WHERE document_id = ? ORDER BY id ASC",
                (document_id,),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def document_unit_counts(self, document_id: int) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT unit_type, COUNT(*) AS count
                FROM content_units
                WHERE document_id = ?
                GROUP BY unit_type
                """,
                (document_id,),
            ).fetchall()
        counts = {"section": 0, "figure": 0, "table": 0}
        for row in rows:
            unit_type = str(row["unit_type"])
            counts[unit_type] = int(row["count"])
        return counts

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
                conn.execute(
                    f"DELETE FROM content_embeddings WHERE content_unit_id IN ({placeholders})",
                    content_ids,
                )
            conn.execute("DELETE FROM content_units WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    def delete_document_with_content_ids(self, document_id: int) -> list[int]:
        content_ids = self.document_content_unit_ids(document_id)
        self.delete_document(document_id)
        return content_ids

    def clear_with_content_ids(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM content_units ORDER BY id ASC").fetchall()
        content_ids = [int(row["id"]) for row in rows]
        self.clear()
        return content_ids

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM term_postings")
            conn.execute("DELETE FROM content_embeddings")
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

    def all_content_unit_texts(self) -> list[tuple[int, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, text_content
                FROM content_units
                ORDER BY id ASC
                """
            ).fetchall()
        return [(int(row["id"]), str(row["text_content"])) for row in rows]

    def content_units_by_ids(self, content_unit_ids: list[int]) -> list[sqlite3.Row]:
        if not content_unit_ids:
            return []
        placeholders = ", ".join("?" for _ in content_unit_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT cu.id AS content_unit_id,
                       cu.document_id,
                       cu.unit_type,
                       cu.page_number,
                       cu.section_name,
                       cu.text_content,
                       cu.caption,
                       cu.image_mime,
                       cu.image_data,
                       cu.token_count,
                       d.source_path AS document_path,
                       d.filename
                FROM content_units cu
                JOIN documents d ON d.id = cu.document_id
                WHERE cu.id IN ({placeholders})
                """,
                content_unit_ids,
            ).fetchall()
            return rows

    def content_units_for_document(self, document_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    cu.id AS content_unit_id,
                    cu.document_id,
                    cu.unit_type,
                    cu.page_number,
                    cu.section_name,
                    cu.text_content,
                    cu.caption,
                    cu.image_mime,
                    cu.image_data,
                    d.source_path AS document_path,
                    d.filename
                FROM content_units cu
                JOIN documents d ON d.id = cu.document_id
                WHERE cu.document_id = ?
                ORDER BY
                    COALESCE(cu.page_number, 0) ASC,
                    CASE cu.unit_type
                        WHEN 'section' THEN 1
                        WHEN 'figure' THEN 2
                        WHEN 'table' THEN 3
                        ELSE 9
                    END ASC,
                    cu.id ASC
                """,
                (document_id,),
            ).fetchall()
        return rows

    def document_content_unit_texts(self, document_id: int) -> list[tuple[int, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, text_content
                FROM content_units
                WHERE document_id = ?
                ORDER BY id ASC
                """,
                (document_id,),
            ).fetchall()
        return [(int(row["id"]), str(row["text_content"])) for row in rows]

    def stats(self) -> dict[str, object]:
        with self.connect() as conn:
            document_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            content_unit_count = int(conn.execute("SELECT COUNT(*) FROM content_units").fetchone()[0])
            term_posting_count = int(conn.execute("SELECT COUNT(*) FROM term_postings").fetchone()[0])
            embedding_count = int(conn.execute("SELECT COUNT(*) FROM content_embeddings").fetchone()[0])
            unit_type_rows = conn.execute(
                """
                SELECT unit_type, COUNT(*) AS count
                FROM content_units
                GROUP BY unit_type
                """
            ).fetchall()
        unit_type_counts = {"section": 0, "figure": 0, "table": 0}
        for row in unit_type_rows:
            unit_type_counts[str(row["unit_type"])] = int(row["count"])
        faiss_path = faiss_path_for_db(self.db_path)
        faiss_exists = faiss_path.exists()
        return {
            "document_count": document_count,
            "content_unit_count": content_unit_count,
            "term_posting_count": term_posting_count,
            "embedding_count": embedding_count,
            "unit_type_counts": unit_type_counts,
            "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            "faiss_exists": faiss_exists,
            "faiss_size_bytes": faiss_path.stat().st_size if faiss_exists else 0,
        }
