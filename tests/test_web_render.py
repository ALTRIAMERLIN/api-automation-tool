from fastapi.testclient import TestClient

from apitool.web.app import create_app

HOST = "http://127.0.0.1:8000"

# Every field from SPEC 5.1, plus the secret inputs of SPEC 5.3.
JOB_FIELDS = [
    "name",
    "url",
    "query_params",
    "headers",
    "auth_type",
    "auth_key_name",
    "auth_username",
    "pagination_type",
    "page_param",
    "page_size_param",
    "start_page",
    "offset_param",
    "limit_param",
    "cursor_param",
    "cursor_path",
    "next_url_path",
    "page_size",
    "records_path",
    "max_pages",
    "timeout_seconds",
    "fields",
    "renames",
    "dedup_key",
    "incremental",
    "export_format",
    "secret",
    "clear_secret",
    "csrf_token",
]


def _setup(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url=HOST)
    client.post("/demo/setup", data={"csrf_token": app.state.csrf_token})
    client.post(
        f"/jobs/{app.state.storage.get_job_by_name('Demo Orders').id}/run",
        data={"csrf_token": app.state.csrf_token},
    )
    return app, client


# AC-44: every page loads the shared assets, and the form has every field
def test_every_get_page_loads_style_and_script(tmp_path):
    app, client = _setup(tmp_path)
    job_id = app.state.storage.get_job_by_name("Demo Orders").id
    pages = ["/", "/jobs/new", f"/jobs/{job_id}/edit", "/runs", "/runs/1"]
    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "/static/style.css" in response.text, path
        assert "/static/app.js" in response.text, path


def test_job_form_contains_every_field(tmp_path):
    app, client = _setup(tmp_path)
    job_id = app.state.storage.get_job_by_name("Demo Orders").id
    page = client.get(f"/jobs/{job_id}/edit").text
    for field in JOB_FIELDS:
        assert f'name="{field}"' in page, field


def test_auth_and_pagination_inputs_carry_show_for(tmp_path):
    app, client = _setup(tmp_path)
    page = client.get("/jobs/new").text
    for value in [
        'data-show-for="api_key_header api_key_query"',
        'data-show-for="basic"',
        'data-show-for="api_key_header api_key_query bearer basic"',
        'data-show-for="page"',
        'data-show-for="offset"',
        'data-show-for="cursor"',
        'data-show-for="next_url"',
    ]:
        assert value in page, value


def test_static_script_is_served(tmp_path):
    app, client = _setup(tmp_path)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "data-show-for" in response.text
    assert "data-confirm" in response.text


def test_no_inline_handlers_in_templates(tmp_path):
    app, client = _setup(tmp_path)
    job_id = app.state.storage.get_job_by_name("Demo Orders").id
    for path in ["/", "/jobs/new", f"/jobs/{job_id}/edit", "/runs", "/runs/1"]:
        text = client.get(path).text
        assert " onclick=" not in text, path
        assert " onsubmit=" not in text, path
