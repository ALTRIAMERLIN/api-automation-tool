"""Runs one job end to end: fetch, transform, export, state and run log (SPEC 12).

This is the only module that combines storage with the engine. The web layer and the CLI call
run_job and preview_job and contain no fetch or transform logic.
"""

import base64
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from apitool import export, pagination, pipeline
from apitool.config import JobConfig
from apitool.demo.api import DemoApi
from apitool.errors import AppError, ConfigError, JobNotFoundError
from apitool.http_client import Fetcher
from apitool.pagination import Progress
from apitool.redact import install_filter, redact, register_secrets, unregister_secrets
from apitool.storage import RunStats, Storage
from apitool.timeutil import format_ts
from apitool.transform import render_csv, to_record

__all__ = [
    "DEMO_HOST",
    "PreviewResult",
    "RunResult",
    "format_ts",
    "make_transport",
    "preview_job",
    "resolve_secret",
    "run_job",
    "utc_now",
]

DEMO_HOST = "demo.api-automation-tool.local"
PREVIEW_ROWS = 10
_ENV_REF_RE = re.compile(r"env:([A-Za-z_][A-Za-z0-9_]*)")
_logger = logging.getLogger("apitool")


@dataclass
class RunResult:
    run_id: int
    status: str
    message: str | None
    warnings: list[str] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    exit_code: int = 0


@dataclass
class PreviewResult:
    records_count: int
    columns: list[str]
    rows: list[list[str]]
    error_type: str | None = None
    error_message: str | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


def make_transport(url: str, dataset_version: int) -> httpx.BaseTransport:
    """Demo host goes to the in-process fake API. Everything else uses real HTTPS (SPEC 6.1)."""
    host = urlsplit(url).hostname or ""
    if host == DEMO_HOST:
        return httpx.MockTransport(DemoApi(dataset_version).handle)
    return httpx.HTTPTransport()


def resolve_secret(raw: str | None) -> str | None:
    """Return the secret value. ``env:NAME`` is read from the environment (SPEC 5.3)."""
    if raw is None:
        return None
    match = _ENV_REF_RE.fullmatch(raw)
    if match is None:
        return raw
    name = match.group(1)
    value = os.environ.get(name)
    if not value:
        raise ConfigError([("secret", f"environment variable {name} is not set")])
    return value


def _secret_for(storage: Storage, job_id: int, cfg: JobConfig) -> str | None:
    if cfg.auth_type == "none":
        return None
    return resolve_secret(storage.get_secret(job_id))


def _redaction_values(cfg: JobConfig, secret: str | None) -> list[str]:
    values: list[str] = []
    if secret:
        values.append(secret)
        if cfg.auth_type == "basic":
            token = base64.b64encode(f"{cfg.auth_username}:{secret}".encode()).decode("ascii")
            values.append(token)
    return values


def _dataset_version(storage: Storage) -> int:
    return int(storage.get_setting("demo_dataset_version", "1"))


def _union_columns(flat: list[dict]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for record in flat:
        for key in record:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def _failure_stats(progress: Progress, fetcher: Fetcher | None) -> RunStats:
    return RunStats(
        pages_fetched=progress.pages_fetched,
        records_fetched=progress.records_fetched,
        retries=fetcher.retries if fetcher is not None else 0,
    )


def run_job(
    storage: Storage,
    job_id: int,
    trigger: str,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime] | None = None,
) -> RunResult:
    """Run a job once and record the result. AppErrors become a failed run; they are not raised.

    JobNotFoundError and JobBusyError are raised before any run record exists.
    """
    install_filter()
    now_fn = now if now is not None else utc_now
    sleep_fn = sleep if sleep is not None else _default_sleep

    job = storage.get_job(job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    cfg = job.config

    started = now_fn()
    run_id = storage.start_run(job_id, job.name, trigger, started)
    _logger.info("run %d started job=%s", run_id, job.name)

    progress = Progress()
    fetcher: Fetcher | None = None
    redaction: list[str] = []
    try:
        secret = _secret_for(storage, job_id, cfg)
        redaction = _redaction_values(cfg, secret)
        register_secrets(redaction)

        url_transport = transport
        if url_transport is None:
            url_transport = make_transport(cfg.url, _dataset_version(storage))
        fetcher = Fetcher(cfg, secret, url_transport, sleep_fn)
        with fetcher:
            fetched = pagination.fetch_all(cfg, fetcher, progress)

        stored_keys = storage.get_seen_keys(job_id) if cfg.incremental else set()
        built = pipeline.build_rows(fetched.records, cfg, stored_keys)
        warnings = [*fetched.warnings, *built.warnings]
        stats = RunStats(
            pages_fetched=progress.pages_fetched,
            records_fetched=progress.records_fetched,
            retries=fetcher.retries,
            duplicates_removed=built.duplicates_removed,
            records_missing_key=built.records_missing_key,
            already_seen_skipped=built.already_seen_skipped,
            records_exported=built.records_exported,
        )

        output_file: str | None = None
        if built.records_exported == 0:
            message = "No records to export"
        else:
            output_file = export.export_filename(job.name, started, run_id, cfg.export_format)
            path = storage.exports_dir / output_file
            if cfg.export_format == "xlsx":
                warnings.extend(export.write_xlsx(path, built.header, built.rows))
            else:
                warnings.extend(export.write_csv(path, built.header, built.rows))
            message = f"Exported {built.records_exported} records to {output_file}"

        for warning in warnings:
            _logger.warning("run %d warning: %s", run_id, warning)

        keys = built.exported_keys if cfg.incremental else []
        storage.finish_run_success(
            run_id,
            stats,
            output_file,
            message,
            warnings,
            now_fn(),
            job_id,
            keys,
            cfg.incremental,
        )
        _logger.info("run %d finished status=success exported=%d", run_id, built.records_exported)
        return RunResult(run_id, "success", message, warnings, None, None, 0)

    except AppError as err:
        message = redact(err.message, redaction)
        error_type = type(err).__name__
        storage.finish_run_failed(
            run_id, _failure_stats(progress, fetcher), error_type, message, now_fn()
        )
        _logger.error("run %d failed: %s: %s", run_id, error_type, message)
        return RunResult(run_id, "failed", None, [], error_type, message, err.exit_code)

    except Exception as exc:
        storage.finish_run_failed(
            run_id,
            _failure_stats(progress, fetcher),
            "InternalError",
            f"unexpected error: {type(exc).__name__}",
            now_fn(),
        )
        _logger.error(
            "run %d failed: InternalError: unexpected error: %s",
            run_id,
            type(exc).__name__,
            exc_info=True,
        )
        raise

    finally:
        unregister_secrets(redaction)


def preview_job(
    storage: Storage,
    job_id: int,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] | None = None,
) -> PreviewResult:
    """Fetch the first page only. Nothing is written: no run record, no state, no file."""
    install_filter()
    sleep_fn = sleep if sleep is not None else _default_sleep

    job = storage.get_job(job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    cfg = job.config

    redaction: list[str] = []
    try:
        secret = _secret_for(storage, job_id, cfg)
        redaction = _redaction_values(cfg, secret)
        register_secrets(redaction)

        url_transport = transport
        if url_transport is None:
            url_transport = make_transport(cfg.url, _dataset_version(storage))
        with Fetcher(cfg, secret, url_transport, sleep_fn) as fetcher:
            records = pagination.fetch_first_page(cfg, fetcher)

        flat: list[dict[str, Any]] = [to_record(item) for item in records]
        columns = _union_columns(flat)
        rows = [[render_csv(record.get(c)) for c in columns] for record in flat[:PREVIEW_ROWS]]
        return PreviewResult(len(records), columns, rows)

    except AppError as err:
        return PreviewResult(0, [], [], type(err).__name__, redact(err.message, redaction))

    finally:
        unregister_secrets(redaction)
