from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from app.config import get_settings


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def slugify_path(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]


class GlobalStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.app_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.source_db_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.settings.app_db_path)
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
                CREATE TABLE IF NOT EXISTS source_roots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL,
                    db_path TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_root_id INTEGER NOT NULL,
                    document_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY(source_root_id) REFERENCES source_roots(id),
                    UNIQUE(source_root_id, document_path)
                );

                CREATE TABLE IF NOT EXISTS service_heartbeats (
                    service_name TEXT PRIMARY KEY,
                    last_seen TEXT NOT NULL,
                    detail TEXT
                );
                """
            )

    def ensure_source_root(self, source_path: Path) -> sqlite3.Row:
        source_type = "directory" if source_path.is_dir() else "file"
        db_name = f"{slugify_path(str(source_path.resolve()))}.sqlite3"
        db_path = str((self.settings.source_db_dir / db_name).resolve())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO source_roots(source_path, source_type, db_path, status, created_at)
                VALUES(?, ?, ?, 'ready', ?)
                """,
                (str(source_path.resolve()), source_type, db_path, utc_now()),
            )
            row = conn.execute(
                "SELECT * FROM source_roots WHERE source_path = ?",
                (str(source_path.resolve()),),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to create source root")
        return row

    def list_source_roots(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM source_roots ORDER BY created_at DESC"
            ).fetchall()
        return rows

    def get_source_root(self, source_root_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_roots WHERE id = ?",
                (source_root_id,),
            ).fetchone()
        return row

    def delete_source_root(self, source_root_id: int) -> sqlite3.Row | None:
        row = self.get_source_root(source_root_id)
        if row is None:
            return None
        with self.connect() as conn:
            conn.execute("DELETE FROM ingestion_jobs WHERE source_root_id = ?", (source_root_id,))
            conn.execute("DELETE FROM source_roots WHERE id = ?", (source_root_id,))
        return row

    def enqueue_document(self, source_root_id: int, document_path: Path) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO ingestion_jobs(
                    source_root_id, document_path, status, created_at
                ) VALUES(?, ?, 'pending', ?)
                """,
                (source_root_id, str(document_path.resolve()), utc_now()),
            )

    def list_jobs(self, source_root_id: int | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM ingestion_jobs"
        params: tuple[object, ...] = ()
        if source_root_id is not None:
            query += " WHERE source_root_id = ?"
            params = (source_root_id,)
        query += " ORDER BY id DESC"
        with self.connect() as conn:
            return conn.execute(query, params).fetchall()

    def job_status_counts(self, source_root_id: int | None = None) -> dict[str, int]:
        query = """
            SELECT status, COUNT(*) AS count
            FROM ingestion_jobs
        """
        params: tuple[object, ...] = ()
        if source_root_id is not None:
            query += " WHERE source_root_id = ?"
            params = (source_root_id,)
        query += " GROUP BY status"
        counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        for row in rows:
            counts[str(row["status"])] = int(row["count"])
        return counts

    def take_next_job(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ingestion_jobs
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'running', started_at = ?
                WHERE id = ?
                """,
                (utc_now(), row["id"]),
            )
            return conn.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ?",
                (row["id"],),
            ).fetchone()

    def mark_job_done(self, job_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'done', finished_at = ?, error_message = NULL
                WHERE id = ?
                """,
                (utc_now(), job_id),
            )

    def mark_job_failed(self, job_id: int, error_message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'failed', finished_at = ?, error_message = ?
                WHERE id = ?
                """,
                (utc_now(), error_message[:1000], job_id),
            )

    def retry_job(self, job_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'pending',
                    error_message = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    created_at = ?
                WHERE id = ?
                """,
                (utc_now(), job_id),
            )

    def retry_failed_jobs(self, source_root_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'pending',
                    error_message = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    created_at = ?
                WHERE source_root_id = ? AND status = 'failed'
                """,
                (utc_now(), source_root_id),
            )

    def touch_service_heartbeat(self, service_name: str, detail: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_heartbeats(service_name, last_seen, detail)
                VALUES(?, ?, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    detail = excluded.detail
                """,
                (service_name, utc_now(), detail[:500]),
            )

    def service_heartbeats(self) -> dict[str, sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM service_heartbeats").fetchall()
        return {str(row["service_name"]): row for row in rows}
