from datetime import UTC, datetime

import pytest

from apitool.config import build_job_config
from apitool.storage import RunStats, Storage

NOW = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)

BASE = {
    "name": "Demo Orders",
    "url": "https://demo.api-automation-tool.local/v1/orders",
    "auth_type": "api_key_header",
    "auth_key_name": "X-API-Key",
    "pagination_type": "page",
    "page_size": 4,
    "records_path": "data",
    "dedup_key": "id",
    "incremental": True,
}


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


def _cfg(**overrides):
    return build_job_config({**BASE, **overrides})


def _success(store, job_id, keys, incremental=True):
    run_id = store.start_run(job_id, "x", "ui", NOW)
    store.finish_run_success(
        run_id,
        RunStats(records_exported=len(keys)),
        "f.csv",
        "ok",
        [],
        NOW,
        job_id,
        keys,
        incremental,
    )
    return run_id


# AC-29: sync state
def test_seen_keys_empty_at_first(store):
    job_id = store.create_job(_cfg(), NOW)
    assert store.get_seen_keys(job_id) == set()


def test_success_commits_exported_keys(store):
    job_id = store.create_job(_cfg(), NOW)
    _success(store, job_id, ["1001", "1002"])
    assert store.get_seen_keys(job_id) == {"1001", "1002"}


def test_failed_run_commits_no_keys(store):
    job_id = store.create_job(_cfg(), NOW)
    run_id = store.start_run(job_id, "x", "ui", NOW)
    store.finish_run_failed(run_id, RunStats(), "HttpError", "x", NOW)
    assert store.get_seen_keys(job_id) == set()


def test_non_incremental_success_commits_no_keys(store):
    job_id = store.create_job(_cfg(incremental=False), NOW)
    _success(store, job_id, ["1001"], incremental=False)
    assert store.get_seen_keys(job_id) == set()


def test_reset_state_empties_keys(store):
    job_id = store.create_job(_cfg(), NOW)
    _success(store, job_id, ["1001", "1002"])
    store.reset_state(job_id)
    assert store.get_seen_keys(job_id) == set()


def test_keys_are_per_job(store):
    first = store.create_job(_cfg(name="One"), NOW)
    second = store.create_job(_cfg(name="Two"), NOW)
    _success(store, first, ["1001"])
    assert store.get_seen_keys(second) == set()
    store.reset_state(second)
    assert store.get_seen_keys(first) == {"1001"}


# AC-36 (storage half): automatic reset on state-relevant changes
@pytest.mark.parametrize(
    "change",
    [
        {"url": "https://demo.api-automation-tool.local/v1/other"},
        {"records_path": "items"},
        {"dedup_key": "sku"},
        {"incremental": False},
    ],
)
def test_state_relevant_change_resets_keys(store, change):
    job_id = store.create_job(_cfg(), NOW)
    _success(store, job_id, ["1001"])
    state_reset = store.update_job(job_id, _cfg(**change), NOW)
    assert state_reset is True
    assert store.get_seen_keys(job_id) == set()


@pytest.mark.parametrize(
    "change",
    [{"name": "Renamed"}, {"export_format": "xlsx"}, {"max_pages": 7}],
)
def test_other_change_keeps_keys(store, change):
    job_id = store.create_job(_cfg(), NOW)
    _success(store, job_id, ["1001"])
    state_reset = store.update_job(job_id, _cfg(**change), NOW)
    assert state_reset is False
    assert store.get_seen_keys(job_id) == {"1001"}
