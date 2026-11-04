"""SQLite storage: schema, jobs, secrets and settings (SPEC 13).

Run, sync-state and export queries are added in later tasks. This module is the only one that
runs SQL. Every statement uses ? placeholders.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from apitool.config import JobConfig, build_job_config
from apitool.errors import ConfigError
from apitool.timeutil import format_ts

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS secrets (
  job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
  job_name TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('ui','cli')),
  status TEXT NOT NULL CHECK (status IN ('running','success','failed')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  pages_fetched INTEGER NOT NULL DEFAULT 0,
  records_fetched INTEGER NOT NULL DEFAULT 0,
  retries INTEGER NOT NULL DEFAULT 0,
  duplicates_removed INTEGER NOT NULL DEFAULT 0,
  records_missing_key INTEGER NOT NULL DEFAULT 0,
  already_seen_skipped INTEGER NOT NULL DEFAULT 0,
  records_exported INTEGER NOT NULL DEFAULT 0,
  output_file TEXT,
  message TEXT,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  error_type TEXT,
  error_message TEXT
);
CREATE TABLE IF NOT EXISTS seen_keys (
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  first_run_id INTEGER NOT NULL,
  PRIMARY KEY (job_id, key)
);
CREATE TABLE IF NOT EXISTS settings (
  name TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

_DUPLICATE_NAME = ("name", "a job with this name already exists")


@dataclass
class JobRecord:
    id: int
    name: str
    config: JobConfig
    created_at: str
    updated_at: str


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        name=row["name"],
        config=build_job_config(json.loads(row["config_json"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class Storage:
    """Owns the SQLite file under data_dir. Each operation opens and closes its own connection."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "apitool.db"
        self.exports_dir = self.data_dir / "exports"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Jobs

    def create_job(self, cfg: JobConfig, now: datetime) -> int:
        stamp = format_ts(now)
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO jobs (name, name_key, config_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cfg.name, cfg.name.lower(), cfg.model_dump_json(), stamp, stamp),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            raise ConfigError([_DUPLICATE_NAME]) from None

    def get_job(self, job_id: int) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def get_job_by_name(self, name: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE name_key = ?", (name.strip().lower(),)
            ).fetchone()
        return _job_from_row(row) if row else None

    def list_jobs(self) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY name_key").fetchall()
        return [_job_from_row(row) for row in rows]

    def update_job(self, job_id: int, cfg: JobConfig, now: datetime) -> bool:
        """Save a changed config. Returns True when the sync state was reset (added in T18)."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE jobs SET name = ?, name_key = ?, config_json = ?, updated_at = ? "
                    "WHERE id = ?",
                    (cfg.name, cfg.name.lower(), cfg.model_dump_json(), format_ts(now), job_id),
                )
        except sqlite3.IntegrityError:
            raise ConfigError([_DUPLICATE_NAME]) from None
        return False

    def delete_job(self, job_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # Secrets

    def set_secret(self, job_id: int, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO secrets (job_id, value) VALUES (?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET value = excluded.value",
                (job_id, value),
            )

    def get_secret(self, job_id: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM secrets WHERE job_id = ?", (job_id,)).fetchone()
        return row["value"] if row else None

    def delete_secret(self, job_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM secrets WHERE job_id = ?", (job_id,))

    # Settings

    def get_setting(self, name: str, default: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE name = ?", (name,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, name: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (name, value),
            )
