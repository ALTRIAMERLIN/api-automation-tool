import time

import pytest

from apitool import cli, pipeline
from apitool.config import build_job_config
from apitool.storage import Storage

DEMO = "https://demo.api-automation-tool.local"


@pytest.fixture
def data_dir(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    # Retries would wait 1 + 2 + 4 seconds. Make sleep instant (PLAN T21).
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def _main(data_dir, *args):
    return cli.main(["--data-dir", data_dir, *args])


def _storage(data_dir):
    return Storage(data_dir)


def _add_job(data_dir, **overrides):
    data = {
        "name": "Probe",
        "url": f"{DEMO}/v1/x",
        "pagination_type": "none",
        "records_path": "data",
    }
    data.update(overrides)
    storage = _storage(data_dir)
    job_id = storage.create_job(build_job_config(data), cli.utc_now())
    return storage, job_id


# AC-37: CLI behavior through cli.main
def test_version(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "apitool 1.0.0"


def test_demo_setup_is_idempotent(data_dir, capsys):
    assert _main(data_dir, "demo-setup") == 0
    assert capsys.readouterr().out.strip() == "Demo jobs ready: 5 created, 0 already existed"
    assert _main(data_dir, "demo-setup") == 0
    assert capsys.readouterr().out.strip() == "Demo jobs ready: 0 created, 5 already existed"


def test_list_jobs_sorted_and_tab_separated(data_dir, capsys):
    _main(data_dir, "demo-setup")
    capsys.readouterr()
    assert _main(data_dir, "list-jobs") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[0] for line in lines] == [
        "Demo Customers",
        "Demo Events",
        "Demo Flaky Orders",
        "Demo Orders",
        "Demo Products",
    ]
    assert lines[0] == "Demo Customers\toffset\txlsx"


def test_run_demo_orders_twice(data_dir, capsys):
    _main(data_dir, "demo-setup")
    capsys.readouterr()

    assert _main(data_dir, "run", "--job", "demo orders") == 0
    out = capsys.readouterr().out
    assert out.startswith("Run 1 success: Exported 8 records to demo-orders_")
    assert (
        "warning: missing_key: 1 records skipped because key field 'id' was missing or empty"
        in out.splitlines()
    )

    assert _main(data_dir, "run", "--job", "demo orders") == 0
    assert capsys.readouterr().out.startswith("Run 2 success: No records to export")


def test_unknown_job_is_usage_error(data_dir, capsys):
    assert _main(data_dir, "run", "--job", "Nope") == 2
    assert "no job named 'Nope'" in capsys.readouterr().err


def test_run_without_job_is_usage_error(data_dir):
    assert _main(data_dir, "run") == 2


def test_failed_run_prints_error_and_exits_one(data_dir, capsys):
    _add_job(data_dir, name="Always Fail", url=f"{DEMO}/v1/always-500")
    assert _main(data_dir, "run", "--job", "Always Fail") == 1
    err = capsys.readouterr().err
    assert (
        "Run 1 failed: HttpError: HTTP 500 from https://demo.api-automation-tool.local/v1/always-500"
        in err
    )


def test_missing_environment_secret_exits_two(data_dir, monkeypatch, capsys):
    monkeypatch.delenv("APITOOL_TEST_MISSING_VAR", raising=False)
    storage, job_id = _add_job(
        data_dir,
        name="Env Job",
        url=f"{DEMO}/v1/orders",
        auth_type="api_key_header",
        auth_key_name="X-API-Key",
    )
    storage.set_secret(job_id, "env:APITOOL_TEST_MISSING_VAR")
    assert _main(data_dir, "run", "--job", "Env Job") == 2
    assert "environment variable APITOOL_TEST_MISSING_VAR is not set" in capsys.readouterr().err


def test_unexpected_error_exits_three(data_dir, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(pipeline, "build_rows", boom)
    _main(data_dir, "demo-setup")
    capsys.readouterr()
    assert _main(data_dir, "run", "--job", "demo orders") == 3
    assert "internal error: ZeroDivisionError" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("job_name", "secret"),
    [("Demo Orders", "super-secret-XYZ-123"), ("Demo Events", "query-secret-ABC-789")],
)
def test_cli_output_never_shows_the_secret(data_dir, capsys, job_name, secret):
    _main(data_dir, "demo-setup")
    storage = _storage(data_dir)
    storage.set_secret(storage.get_job_by_name(job_name).id, secret)
    capsys.readouterr()
    assert _main(data_dir, "run", "--job", job_name) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


# Argument parsing only; serve itself is never started in tests (PLAN T21)
def test_serve_port_below_1024_is_usage_error(data_dir):
    assert _main(data_dir, "serve", "--port", "80") == 2


def test_serve_port_must_be_a_number(data_dir):
    assert _main(data_dir, "serve", "--port", "abc") == 2


def test_no_command_is_usage_error():
    assert cli.main([]) == 2
