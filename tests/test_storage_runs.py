from datetime import UTC, datetime, timedelta

import pytest

from apitool.config import build_job_config
from apitool.errors import JobBusyError
from apitool.storage import RunStats, Storage

NOW = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


@pytest.fixture
def job_id(store):
    cfg = build_job_config(
        {
            "name": "Demo Orders",
            "url": "https://demo.api-automation-tool.local/v1/orders",
            "pagination_type": "page",
            "records_path": "data",
        }
    )
    return store.create_job(cfg, NOW)


def test_start_run_inserts_running_row(store, job_id):
    run_id = store.start_run(job_id, "Demo Orders", "ui", NOW)
    run = store.get_run(run_id)
    assert run.status == "running"
    assert run.job_id == job_id
    assert run.job_name == "Demo Orders"
    assert run.trigger == "ui"
    assert run.started_at == "2026-11-04T10:00:00Z"
    assert run.finished_at is None


def test_finish_success_sets_every_column(store, job_id):
    run_id = store.start_run(job_id, "Demo Orders", "cli", NOW)
    stats = RunStats(
        pages_fetched=3,
        records_fetched=11,
        retries=1,
        duplicates_removed=2,
        records_missing_key=1,
        already_seen_skipped=0,
        records_exported=8,
    )
    finished = NOW + timedelta(seconds=5)
    store.finish_run_success(
        run_id,
        stats,
        "demo-orders_20261104-100000_run1.csv",
        "Exported 8 records to demo-orders_20261104-100000_run1.csv",
        ["missing_key: 1 records skipped because key field 'id' was missing or empty"],
        finished,
        job_id,
        [],
        False,
    )
    run = store.get_run(run_id)
    assert run.status == "success"
    assert (run.pages_fetched, run.records_fetched, run.retries) == (3, 11, 1)
    assert (run.duplicates_removed, run.records_missing_key) == (2, 1)
    assert (run.already_seen_skipped, run.records_exported) == (0, 8)
    assert run.output_file == "demo-orders_20261104-100000_run1.csv"
    assert run.message.startswith("Exported 8 records")
    assert run.warnings == [
        "missing_key: 1 records skipped because key field 'id' was missing or empty"
    ]
    assert run.finished_at == "2026-11-04T10:00:05Z"
    assert run.error_type is None and run.error_message is None


def test_finish_failed_sets_error_and_no_output(store, job_id):
    run_id = store.start_run(job_id, "Demo Orders", "ui", NOW)
    store.finish_run_failed(
        run_id,
        RunStats(retries=3),
        "HttpError",
        "HTTP 500 from https://demo.api-automation-tool.local/v1/always-500",
        NOW + timedelta(seconds=9),
    )
    run = store.get_run(run_id)
    assert run.status == "failed"
    assert run.retries == 3
    assert run.error_type == "HttpError"
    assert run.error_message.startswith("HTTP 500 from")
    assert run.output_file is None
    assert run.finished_at == "2026-11-04T10:00:09Z"


def test_second_run_of_same_job_while_running_is_busy(store, job_id):
    store.start_run(job_id, "Demo Orders", "ui", NOW)
    with pytest.raises(JobBusyError):
        store.start_run(job_id, "Demo Orders", "cli", NOW + timedelta(seconds=1))


def test_run_after_finish_is_allowed(store, job_id):
    first = store.start_run(job_id, "Demo Orders", "ui", NOW)
    store.finish_run_failed(first, RunStats(), "HttpError", "x", NOW)
    second = store.start_run(job_id, "Demo Orders", "ui", NOW + timedelta(seconds=1))
    assert second > first


def test_run_two_hours_one_minute_old_is_marked_interrupted(store, job_id):
    old = store.start_run(job_id, "Demo Orders", "ui", NOW - timedelta(hours=2, minutes=1))
    new = store.start_run(job_id, "Demo Orders", "ui", NOW)
    stale = store.get_run(old)
    assert stale.status == "failed"
    assert stale.error_type == "Interrupted"
    assert stale.error_message == "run did not finish (process stopped)"
    assert store.get_run(new).status == "running"


def test_run_one_hour_fifty_nine_minutes_old_still_blocks(store, job_id):
    recent = store.start_run(job_id, "Demo Orders", "ui", NOW - timedelta(hours=1, minutes=59))
    with pytest.raises(JobBusyError):
        store.start_run(job_id, "Demo Orders", "ui", NOW)
    assert store.get_run(recent).status == "running"


def test_list_runs_is_newest_first_and_limited(store, job_id):
    ids = []
    for minute in range(3):
        run_id = store.start_run(job_id, "Demo Orders", "ui", NOW + timedelta(minutes=minute))
        store.finish_run_failed(run_id, RunStats(), "HttpError", "x", NOW)
        ids.append(run_id)
    assert [r.id for r in store.list_runs(limit=100)] == list(reversed(ids))
    assert [r.id for r in store.list_runs(limit=2)] == [ids[2], ids[1]]
    assert store.last_run_for_job(job_id).id == ids[2]
