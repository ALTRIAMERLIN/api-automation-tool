import sqlite3
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from apitool.config import build_job_config
from apitool.web.app import create_app

HOST = "http://127.0.0.1:8000"


def _app_with_demo(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url=HOST)
    client.post("/demo/setup", data={"csrf_token": app.state.csrf_token})
    return app, client


def _job_id(app, name):
    return app.state.storage.get_job_by_name(name).id


def _run_job(client, app, name):
    return client.post(
        f"/jobs/{_job_id(app, name)}/run",
        data={"csrf_token": app.state.csrf_token},
        follow_redirects=False,
    )


# AC-43: run, detail, download, history and errors
def test_run_demo_orders_redirects_to_detail(tmp_path):
    app, client = _app_with_demo(tmp_path)
    response = _run_job(client, app, "Demo Orders")
    assert response.status_code == 303
    assert response.headers["location"] == "/runs/1"

    page = client.get("/runs/1").text
    assert "Success" in page
    assert "Records exported" in page
    assert "<td>8</td>" in page
    # Jinja escapes the quotes around 'id', so check the parts without them.
    assert "missing_key: 1 records skipped because key field " in page
    assert "was missing or empty" in page
    assert "/runs/1/download" in page


def test_download_returns_the_exported_file(tmp_path):
    app, client = _app_with_demo(tmp_path)
    _run_job(client, app, "Demo Orders")
    run = app.state.storage.get_run(1)
    path = app.state.storage.exports_dir / run.output_file

    response = client.get("/runs/1/download")
    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert "demo-orders_" in response.headers["content-disposition"]


def test_run_history_lists_the_run(tmp_path):
    app, client = _app_with_demo(tmp_path)
    _run_job(client, app, "Demo Orders")
    page = client.get("/runs").text
    assert "/runs/1" in page
    assert "Demo Orders" in page


def test_failed_run_page_shows_error_type_and_message(tmp_path, monkeypatch):
    app, client = _app_with_demo(tmp_path)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    job_id = app.state.storage.create_job(
        build_job_config(
            {
                "name": "Always Fail",
                "url": "https://demo.api-automation-tool.local/v1/always-500",
                "pagination_type": "none",
                "records_path": "data",
            }
        ),
        datetime(2026, 11, 4, tzinfo=UTC),
    )
    response = client.post(
        f"/jobs/{job_id}/run",
        data={"csrf_token": app.state.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"]).text
    assert "HttpError" in page
    assert "HTTP 500 from https://demo.api-automation-tool.local/v1/always-500" in page


def test_unknown_run_is_404(tmp_path):
    _, client = _app_with_demo(tmp_path)
    assert client.get("/runs/999").status_code == 404


def test_download_refuses_path_outside_exports(tmp_path):
    app, client = _app_with_demo(tmp_path)
    _run_job(client, app, "Demo Orders")
    with sqlite3.connect(app.state.storage.db_path) as raw:
        raw.execute("UPDATE runs SET output_file = '../apitool.db' WHERE id = 1")
    assert client.get("/runs/1/download").status_code == 404


def test_run_while_running_is_409(tmp_path):
    app, client = _app_with_demo(tmp_path)
    job_id = _job_id(app, "Demo Orders")
    app.state.storage.start_run(job_id, "Demo Orders", "ui", datetime.now(UTC))
    response = client.post(
        f"/jobs/{job_id}/run",
        data={"csrf_token": app.state.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert "This job is already running." in response.text
