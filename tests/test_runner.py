import csv
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import openpyxl
import pytest

from apitool import pipeline, runner
from apitool.config import build_job_config
from apitool.demo.jobs import DEMO_JOBS, setup_demo_jobs
from apitool.errors import JobNotFoundError
from apitool.runner import make_transport, preview_job, resolve_secret, run_job
from apitool.storage import Storage

EXPECTED = Path(__file__).parent / "fixtures" / "expected"
NOW = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)
DEMO = "https://demo.api-automation-tool.local"
DEDUP_WARNING = "missing_key: 1 records skipped because key field 'id' was missing or empty"


def _fixture(name):
    return json.loads((EXPECTED / name).read_text(encoding="utf-8"))


def _clock():
    """Each call returns the next second after NOW, as SPEC/ACCEPTANCE 1 describes."""
    state = {"n": 0}

    def now():
        value = NOW + timedelta(seconds=state["n"])
        state["n"] += 1
        return value

    return now


@pytest.fixture
def store(tmp_path):
    storage = Storage(tmp_path / "data")
    setup_demo_jobs(storage, NOW)
    return storage


def _job_id(store, name):
    return store.get_job_by_name(name).id


def _same_values_and_types(actual_rows, expected_rows):
    assert len(actual_rows) == len(expected_rows)
    for actual, expected in zip(actual_rows, expected_rows, strict=True):
        assert [type(v) for v in actual] == [type(v) for v in expected], (actual, expected)
        assert actual == expected


def _read_output(path):
    if path.suffix == ".xlsx":
        sheet = openpyxl.load_workbook(path)["data"]
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


# AC-30: the five demo jobs on a fresh database
STATS_EXPECTED = _fixture("run_stats.json")
OUTPUT_FIXTURE = {
    "Demo Orders": "orders_dedup_rows.json",
    "Demo Events": "events_rows.json",
    "Demo Customers": "customers_xlsx.json",
    "Demo Products": "products_xlsx.json",
    "Demo Flaky Orders": "orders_dedup_rows.json",
}


@pytest.mark.parametrize("name", list(STATS_EXPECTED))
def test_demo_job_first_run_matches_fixtures(store, name):
    sleeps = []
    result = run_job(store, _job_id(store, name), "cli", sleep=sleeps.append, now=_clock())
    assert result.status == "success", result.error_message
    run = store.get_run(result.run_id)

    counters = {key: getattr(run, key) for key in STATS_EXPECTED[name]}
    assert counters == STATS_EXPECTED[name]

    expected_warnings = [DEDUP_WARNING] if name in ("Demo Orders", "Demo Flaky Orders") else []
    assert run.warnings == expected_warnings

    expected_sleeps = [0, 0, 0] if name == "Demo Flaky Orders" else []
    assert sleeps == expected_sleeps

    assert re.fullmatch(r"[a-z0-9-]+_\d{8}-\d{6}_run\d+\.(csv|xlsx)", run.output_file), (
        run.output_file
    )
    path = store.exports_dir / run.output_file
    assert path.is_file()
    _same_values_and_types(_read_output(path), _fixture(OUTPUT_FIXTURE[name]))


def test_demo_job_list_matches_spec(store):
    assert [data["name"] for data, _ in DEMO_JOBS] == [
        "Demo Orders",
        "Demo Customers",
        "Demo Events",
        "Demo Products",
        "Demo Flaky Orders",
    ]


# AC-31: failed runs and environment secrets
def _add_job(store, **overrides):
    data = {
        "name": "Probe",
        "url": f"{DEMO}/v1/x",
        "pagination_type": "none",
        "records_path": "data",
    }
    data.update(overrides)
    return store.create_job(build_job_config(data), NOW)


def test_always_500_is_failed_run_with_three_retries(store):
    job_id = _add_job(store, url=f"{DEMO}/v1/always-500", name="Always Fail")
    sleeps = []
    result = run_job(store, job_id, "cli", sleep=sleeps.append, now=_clock())
    run = store.get_run(result.run_id)
    assert result.status == "failed"
    assert run.error_type == "HttpError"
    assert run.retries == 3
    assert run.output_file is None
    assert list(store.exports_dir.iterdir()) == []


def test_offsite_next_url_is_pagination_error(store):
    job_id = _add_job(
        store,
        url=f"{DEMO}/v1/offsite-next",
        pagination_type="next_url",
        next_url_path="links.next",
        records_path="items",
    )
    result = run_job(store, job_id, "cli", sleep=lambda s: None, now=_clock())
    assert result.status == "failed"
    assert result.error_type == "PaginationError"
    assert "different host" in result.error_message


def test_missing_environment_variable_is_config_failure(store, monkeypatch):
    monkeypatch.delenv("APITOOL_TEST_MISSING_VAR", raising=False)
    job_id = _job_id(store, "Demo Orders")
    store.set_secret(job_id, "env:APITOOL_TEST_MISSING_VAR")
    result = run_job(store, job_id, "cli", sleep=lambda s: None, now=_clock())
    assert result.status == "failed"
    assert result.error_type == "ConfigError"
    assert result.exit_code == 2
    assert "environment variable APITOOL_TEST_MISSING_VAR is not set" in result.error_message


def test_environment_secret_that_is_set_succeeds(store, monkeypatch):
    monkeypatch.setenv("APITOOL_TEST_MISSING_VAR", "demo-key-123")
    job_id = _job_id(store, "Demo Orders")
    store.set_secret(job_id, "env:APITOOL_TEST_MISSING_VAR")
    result = run_job(store, job_id, "cli", sleep=lambda s: None, now=_clock())
    assert result.status == "success"
    assert store.get_run(result.run_id).records_exported == 8


def test_resolve_secret_rules(monkeypatch):
    monkeypatch.setenv("APITOOL_TEST_SET", "value-1")
    monkeypatch.setenv("APITOOL_TEST_EMPTY", "")
    assert resolve_secret(None) is None
    assert resolve_secret("plain-text") == "plain-text"
    assert resolve_secret("env:APITOOL_TEST_SET") == "value-1"
    assert resolve_secret("env:not-a-name") == "env:not-a-name"
    with pytest.raises(Exception, match="environment variable APITOOL_TEST_EMPTY is not set"):
        resolve_secret("env:APITOOL_TEST_EMPTY")


# AC-32: redaction in the run row, the logs and the messages
@pytest.mark.parametrize(
    ("name", "secret", "expected_message"),
    [
        (
            "Demo Orders",
            "super-secret-XYZ-123",
            "HTTP 401 from https://demo.api-automation-tool.local/v1/orders",
        ),
        ("Demo Events", "query-secret-ABC-789", None),
    ],
)
def test_secret_never_reaches_run_row_or_logs(store, caplog, name, secret, expected_message):
    job_id = _job_id(store, name)
    store.set_secret(job_id, secret)
    with caplog.at_level(logging.DEBUG):
        result = run_job(store, job_id, "cli", sleep=lambda s: None, now=_clock())

    assert result.status == "failed"
    assert result.error_type == "HttpError"
    if expected_message is not None:
        assert result.error_message == expected_message
    assert "api_key" not in result.error_message
    assert "?" not in result.error_message

    with store._connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM runs").fetchall()]
    assert rows and all(secret not in str(value) for row in rows for value in row.values())
    assert secret not in caplog.text


def test_unexpected_error_is_recorded_and_propagates(store, monkeypatch):
    def boom(*args, **kwargs):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(pipeline, "build_rows", boom)
    job_id = _job_id(store, "Demo Orders")
    with pytest.raises(ZeroDivisionError):
        run_job(store, job_id, "cli", sleep=lambda s: None, now=_clock())
    run = store.list_runs(limit=1)[0]
    assert run.status == "failed"
    assert run.error_type == "InternalError"
    assert run.error_message == "unexpected error: ZeroDivisionError"


def test_missing_job_raises_without_run_record(store):
    with pytest.raises(JobNotFoundError):
        run_job(store, 9999, "cli", sleep=lambda s: None, now=_clock())
    assert store.list_runs() == []


def test_preview_fetches_first_page_and_writes_nothing(store):
    job_id = _job_id(store, "Demo Orders")
    preview = preview_job(store, job_id, sleep=lambda s: None)
    assert preview.error_type is None
    assert preview.records_count == 4
    assert preview.columns == [
        "id",
        "status",
        "total",
        "currency",
        "customer.name",
        "customer.email",
        "tags",
        "shipped",
        "note",
    ]
    assert store.list_runs() == []


def test_runner_re_exports_format_ts_from_timeutil():
    # PLAN T17: runner re-exports format_ts, which lives in timeutil.
    from apitool import timeutil

    assert runner.format_ts is timeutil.format_ts
    assert runner.format_ts(NOW) == "2026-11-04T10:00:00Z"


def test_make_transport_routes_demo_host_only():
    assert isinstance(make_transport(f"{DEMO}/v1/orders", 1), httpx.MockTransport)
    assert isinstance(make_transport("https://api.example.com/x", 1), httpx.HTTPTransport)
    assert runner.DEMO_HOST == "demo.api-automation-tool.local"
