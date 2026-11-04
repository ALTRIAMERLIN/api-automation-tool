import sqlite3
from datetime import UTC, datetime

import pytest

from apitool.config import build_job_config
from apitool.errors import ConfigError
from apitool.storage import Storage

NOW = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)

DEMO_ORDERS = {
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
    return build_job_config({**DEMO_ORDERS, **overrides})


def test_storage_creates_dirs_and_database(tmp_path):
    store = Storage(tmp_path / "data")
    assert store.db_path.is_file()
    assert store.exports_dir.is_dir()


def test_create_get_and_round_trip_config(store):
    cfg = _cfg()
    job_id = store.create_job(cfg, NOW)
    job = store.get_job(job_id)
    assert job.name == "Demo Orders"
    assert job.config == cfg
    assert job.created_at == "2026-11-04T10:00:00Z"
    assert job.updated_at == "2026-11-04T10:00:00Z"


def test_get_job_by_name_is_case_insensitive(store):
    job_id = store.create_job(_cfg(), NOW)
    assert store.get_job_by_name("demo ORDERS").id == job_id
    assert store.get_job_by_name("Nope") is None


def test_duplicate_name_in_other_case_is_config_error(store):
    store.create_job(_cfg(), NOW)
    with pytest.raises(ConfigError) as exc_info:
        store.create_job(_cfg(name="demo orders"), NOW)
    assert exc_info.value.errors == [("name", "a job with this name already exists")]


def test_list_jobs_sorted_by_name_key(store):
    store.create_job(_cfg(name="Zeta"), NOW)
    store.create_job(_cfg(name="alpha"), NOW)
    store.create_job(_cfg(name="Mid"), NOW)
    assert [job.name for job in store.list_jobs()] == ["alpha", "Mid", "Zeta"]


def test_update_job_saves_new_config(store):
    job_id = store.create_job(_cfg(), NOW)
    later = datetime(2026, 11, 4, 11, 0, 0, tzinfo=UTC)
    store.update_job(job_id, _cfg(page_size=10), later)
    job = store.get_job(job_id)
    assert job.config.page_size == 10
    assert job.updated_at == "2026-11-04T11:00:00Z"
    assert job.created_at == "2026-11-04T10:00:00Z"


def test_update_to_duplicate_name_is_config_error(store):
    store.create_job(_cfg(name="Other"), NOW)
    job_id = store.create_job(_cfg(), NOW)
    with pytest.raises(ConfigError) as exc_info:
        store.update_job(job_id, _cfg(name="OTHER"), NOW)
    assert exc_info.value.errors[0][0] == "name"


def test_secret_set_get_replace_and_delete(store):
    job_id = store.create_job(_cfg(), NOW)
    assert store.get_secret(job_id) is None
    store.set_secret(job_id, "first")
    store.set_secret(job_id, "second")
    assert store.get_secret(job_id) == "second"
    store.delete_secret(job_id)
    assert store.get_secret(job_id) is None


def test_delete_job_removes_secret_and_seen_keys_and_keeps_run_name(store):
    job_id = store.create_job(_cfg(), NOW)
    store.set_secret(job_id, "demo-key-123")
    with sqlite3.connect(store.db_path) as raw:
        raw.execute("PRAGMA foreign_keys=ON")
        raw.execute(
            "INSERT INTO seen_keys (job_id, key, first_run_id) VALUES (?, '1001', 1)", (job_id,)
        )
        raw.execute(
            "INSERT INTO runs (job_id, job_name, trigger, status, started_at) "
            "VALUES (?, 'Demo Orders', 'ui', 'success', '2026-11-04T10:00:00Z')",
            (job_id,),
        )
    store.delete_job(job_id)

    with sqlite3.connect(store.db_path) as raw:
        assert raw.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 0
        assert raw.execute("SELECT COUNT(*) FROM seen_keys").fetchone()[0] == 0
        assert raw.execute("SELECT job_id, job_name FROM runs").fetchone() == (None, "Demo Orders")
    assert store.get_job(job_id) is None


def test_settings_default_and_set(store):
    assert store.get_setting("demo_dataset_version", "1") == "1"
    store.set_setting("demo_dataset_version", "2")
    assert store.get_setting("demo_dataset_version", "1") == "2"
