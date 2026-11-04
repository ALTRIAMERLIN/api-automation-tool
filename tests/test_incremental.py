import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apitool import export
from apitool.demo.jobs import setup_demo_jobs
from apitool.errors import ExportError
from apitool.runner import run_job
from apitool.storage import Storage

EXPECTED = Path(__file__).parent / "fixtures" / "expected"
NOW = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)


def _fixture(name):
    return json.loads((EXPECTED / name).read_text(encoding="utf-8"))


def _clock():
    state = {"n": 0}

    def now():
        value = NOW + timedelta(seconds=state["n"])
        state["n"] += 1
        return value

    return now


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


@pytest.fixture
def store(tmp_path):
    storage = Storage(tmp_path / "data")
    setup_demo_jobs(storage, NOW)
    return storage


@pytest.fixture
def orders_id(store):
    return store.get_job_by_name("Demo Orders").id


def _run(store, job_id):
    return run_job(store, job_id, "cli", sleep=lambda s: None, now=_clock())


# AC-34: the ACCEPTANCE 3.9 scenario, step by step
def test_incremental_scenario_matches_table(store, orders_id):
    # Run 1: dataset v1, fresh state.
    r1 = _run(store, orders_id)
    run1 = store.get_run(r1.run_id)
    assert (run1.pages_fetched, run1.records_fetched) == (3, 11)
    assert (run1.duplicates_removed, run1.records_missing_key) == (2, 1)
    assert (run1.already_seen_skipped, run1.records_exported) == (0, 8)
    assert run1.output_file is not None
    assert _read_csv(store.exports_dir / run1.output_file) == _fixture("orders_dedup_rows.json")
    assert len(store.get_seen_keys(orders_id)) == 8

    # Run 2: dataset v1 again, every record is already seen.
    r2 = _run(store, orders_id)
    run2 = store.get_run(r2.run_id)
    assert (run2.pages_fetched, run2.records_fetched) == (3, 11)
    assert (run2.duplicates_removed, run2.records_missing_key) == (2, 1)
    assert (run2.already_seen_skipped, run2.records_exported) == (8, 0)
    assert run2.output_file is None
    assert run2.message == "No records to export"
    assert run2.status == "success"
    assert len(store.get_seen_keys(orders_id)) == 8

    # Switch the demo API to dataset v2.
    store.set_setting("demo_dataset_version", "2")

    # Run 3: v2 adds 1009 to 1011.
    r3 = _run(store, orders_id)
    run3 = store.get_run(r3.run_id)
    assert (run3.pages_fetched, run3.records_fetched) == (4, 14)
    assert (run3.duplicates_removed, run3.records_missing_key) == (2, 1)
    assert (run3.already_seen_skipped, run3.records_exported) == (8, 3)
    assert _read_csv(store.exports_dir / run3.output_file) == _fixture("orders_v2_new_rows.json")
    assert len(store.get_seen_keys(orders_id)) == 11

    # Reset the sync state, then run 4 exports everything from v2.
    store.reset_state(orders_id)
    r4 = _run(store, orders_id)
    run4 = store.get_run(r4.run_id)
    assert (run4.pages_fetched, run4.records_fetched) == (4, 14)
    assert (run4.duplicates_removed, run4.records_missing_key) == (2, 1)
    assert (run4.already_seen_skipped, run4.records_exported) == (0, 11)
    assert _read_csv(store.exports_dir / run4.output_file) == _fixture("orders_v2_full_rows.json")
    assert len(store.get_seen_keys(orders_id)) == 11


# AC-35: a failed export does not commit state
def test_export_failure_commits_no_state(store, orders_id, monkeypatch):
    def failing_write(path, header, rows):
        raise ExportError("could not write export: OSError")

    monkeypatch.setattr(export, "write_csv", failing_write)
    failed = _run(store, orders_id)
    assert failed.status == "failed"
    assert failed.error_type == "ExportError"
    assert store.get_seen_keys(orders_id) == set()

    # Counts reached before the export failed are kept. Nothing was exported.
    failed_run = store.get_run(failed.run_id)
    assert (failed_run.pages_fetched, failed_run.records_fetched) == (3, 11)
    assert (failed_run.duplicates_removed, failed_run.records_missing_key) == (2, 1)
    assert failed_run.records_exported == 0

    monkeypatch.undo()
    recovered = _run(store, orders_id)
    assert recovered.status == "success"
    assert store.get_run(recovered.run_id).records_exported == 8
    assert len(store.get_seen_keys(orders_id)) == 8
