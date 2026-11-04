import time
from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient

from apitool import runner
from apitool.config import build_job_config
from apitool.demo.api import DemoApi
from apitool.web.app import create_app

HOST = "http://127.0.0.1:8000"
HEADERS = [
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


def _app_with_demo(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url=HOST)
    client.post("/demo/setup", data={"csrf_token": app.state.csrf_token})
    return app, client


def _use_demo_api(monkeypatch):
    api = DemoApi(1)
    monkeypatch.setattr(
        runner, "make_transport", lambda url, version: httpx.MockTransport(api.handle)
    )
    return api


def _preview(client, app, name):
    job_id = app.state.storage.get_job_by_name(name).id
    return client.post(f"/jobs/{job_id}/preview", data={"csrf_token": app.state.csrf_token})


# AC-42: preview of Demo Orders
def test_preview_demo_orders_table_and_single_request(tmp_path, monkeypatch):
    app, client = _app_with_demo(tmp_path)
    api = _use_demo_api(monkeypatch)
    response = _preview(client, app, "Demo Orders")
    assert response.status_code == 200
    assert "Page 1 returned 4 records." in response.text
    assert len(api.requests) == 1

    positions = [response.text.index(f"<th>{name}</th>") for name in HEADERS]
    assert positions == sorted(positions)


def test_preview_escapes_formula_text(tmp_path, monkeypatch):
    app, client = _app_with_demo(tmp_path)
    _use_demo_api(monkeypatch)
    text = _preview(client, app, "Demo Orders").text
    assert "=HYPERLINK(&#34;http://evil.example&#34;)" in text or (
        "=HYPERLINK(&quot;http://evil.example&quot;)" in text
    )
    assert '"http://evil.example"' not in text


def test_preview_writes_no_run_row(tmp_path, monkeypatch):
    app, client = _app_with_demo(tmp_path)
    _use_demo_api(monkeypatch)
    _preview(client, app, "Demo Orders")
    assert app.state.storage.list_runs() == []


def test_preview_error_shows_error_type(tmp_path, monkeypatch):
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
    response = client.post(f"/jobs/{job_id}/preview", data={"csrf_token": app.state.csrf_token})
    assert response.status_code == 200
    assert "HttpError" in response.text
    assert "HTTP 500" in response.text
