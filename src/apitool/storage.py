"""SQLite storage: schema, jobs, secrets, settings, runs and sync state (SPEC 13).

This module is the only one that runs SQL. Every statement uses ? placeholders.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from apitool.config import JobConfig, build_job_config
from apitool.errors import ConfigError, JobBusyError, JobNotFoundError
from apitool.timeutil import format_ts

# A change to any of these makes the stored sync state invalid (SPEC 10, automatic reset).
STATE_FIELDS = ("url", "records_path", "dedup_key", "incremental")
STALE_RUN_AFTER = timedelta(hours=2)
INTERRUPTED_MESSAGE = "run did not finish (process stopped)"
BUSY_MESSAGE = "This job is already running."

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


@dataclass
class RunStats:
    pages_fetched: int = 0
    records_fetched: int = 0
    retries: int = 0
    duplicates_removed: int = 0
    records_missing_key: int = 0
    already_seen_skipped: int = 0
    records_exported: int = 0


@dataclass
class RunRecord:
    id: int
    job_id: int | None
    job_name: str
    trigger: str
    status: str
    started_at: str
    finished_at: str | None
    pages_fetched: int
    records_fetched: int
    retries: int
    duplicates_removed: int
    records_missing_key: int
    already_seen_skipped: int
    records_exported: int
    output_file: str | None
    message: str | None
    warnings: list[str] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        id=row["id"],
        job_id=row["job_id"],
        job_name=row["job_name"],
        trigger=row["trigger"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        pages_fetched=row["pages_fetched"],
        records_fetched=row["records_fetched"],
        retries=row["retries"],
        duplicates_removed=row["duplicates_removed"],
        records_missing_key=row["records_missing_key"],
        already_seen_skipped=row["already_seen_skipped"],
        records_exported=row["records_exported"],
        output_file=row["output_file"],
        message=row["message"],
        warnings=json.loads(row["warnings_json"]),
        error_type=row["error_type"],
        error_message=row["error_message"],
    )


def _stats_params(stats: RunStats) -> tuple[int, ...]:
    return (
        stats.pages_fetched,
        stats.records_fetched,
        stats.retries,
        stats.duplicates_removed,
        stats.records_missing_key,
        stats.already_seen_skipped,
        stats.records_exported,
    )


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
    def _connect(self, *, autocommit: bool = False) -> Iterator[sqlite3.Connection]:
        """Open one connection. With autocommit, the caller issues BEGIN and COMMIT itself."""
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None if autocommit else "")
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
        """Save an edited config. Returns True when the sync state was reset (SPEC 10)."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT config_json FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if row is None:
                    raise JobNotFoundError(f"job {job_id} not found")
                old = build_job_config(json.loads(row["config_json"]))
                state_reset = any(getattr(old, f) != getattr(cfg, f) for f in STATE_FIELDS)
                conn.execute(
                    "UPDATE jobs SET name = ?, name_key = ?, config_json = ?, updated_at = ? "
                    "WHERE id = ?",
                    (cfg.name, cfg.name.lower(), cfg.model_dump_json(), format_ts(now), job_id),
                )
                if state_reset:
                    conn.execute("DELETE FROM seen_keys WHERE job_id = ?", (job_id,))
        except sqlite3.IntegrityError:
            raise ConfigError([_DUPLICATE_NAME]) from None
        return state_reset

    # Sync state

    def get_seen_keys(self, job_id: int) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key FROM seen_keys WHERE job_id = ?", (job_id,)).fetchall()
        return {row["key"] for row in rows}

    def reset_state(self, job_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM seen_keys WHERE job_id = ?", (job_id,))

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

    # Runs

    def start_run(self, job_id: int, job_name: str, trigger: str, now: datetime) -> int:
        """Insert a running run. Stale runs are marked failed first (SPEC 12.1 step 2).

        Raises JobBusyError when a run of this job is still running.
        """
        started = format_ts(now)
        stale_before = format_ts(now - STALE_RUN_AFTER)
        with self._connect(autocommit=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE runs SET status = 'failed', error_type = 'Interrupted', "
                "error_message = ?, finished_at = ? "
                "WHERE job_id = ? AND status = 'running' AND started_at < ?",
                (INTERRUPTED_MESSAGE, started, job_id, stale_before),
            )
            busy = conn.execute(
                "SELECT 1 FROM runs WHERE job_id = ? AND status = 'running' LIMIT 1",
                (job_id,),
            ).fetchone()
            if busy:
                conn.execute("COMMIT")
                raise JobBusyError(BUSY_MESSAGE)
            cursor = conn.execute(
                "INSERT INTO runs (job_id, job_name, trigger, status, started_at) "
                "VALUES (?, ?, ?, 'running', ?)",
                (job_id, job_name, trigger, started),
            )
            conn.execute("COMMIT")
            return int(cursor.lastrowid)

    def finish_run_success(
        self,
        run_id: int,
        stats: RunStats,
        output_file: str | None,
        message: str,
        warnings: list[str],
        finished_at: datetime,
        job_id: int,
        exported_keys: list[str],
        incremental: bool,
    ) -> None:
        """Mark a run successful. Exported keys are committed in the same transaction (SPEC 10)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status = 'success', pages_fetched = ?, records_fetched = ?, "
                "retries = ?, duplicates_removed = ?, records_missing_key = ?, "
                "already_seen_skipped = ?, records_exported = ?, output_file = ?, message = ?, "
                "warnings_json = ?, finished_at = ?, error_type = NULL, error_message = NULL "
                "WHERE id = ?",
                (
                    *_stats_params(stats),
                    output_file,
                    message,
                    json.dumps(warnings),
                    format_ts(finished_at),
                    run_id,
                ),
            )
            if incremental:
                conn.executemany(
                    "INSERT OR IGNORE INTO seen_keys (job_id, key, first_run_id) VALUES (?, ?, ?)",
                    [(job_id, key, run_id) for key in exported_keys],
                )

    def finish_run_failed(
        self,
        run_id: int,
        stats: RunStats,
        error_type: str,
        error_message: str,
        finished_at: datetime,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status = 'failed', pages_fetched = ?, records_fetched = ?, "
                "retries = ?, duplicates_removed = ?, records_missing_key = ?, "
                "already_seen_skipped = ?, records_exported = ?, output_file = NULL, "
                "error_type = ?, error_message = ?, finished_at = ? WHERE id = ?",
                (
                    *_stats_params(stats),
                    error_type,
                    error_message,
                    format_ts(finished_at),
                    run_id,
                ),
            )

    def get_run(self, run_id: int) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row) if row else None

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def last_run_for_job(self, job_id: int) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
            ).fetchone()
        return _run_from_row(row) if row else None
