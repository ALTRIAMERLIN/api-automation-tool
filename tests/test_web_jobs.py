from fastapi.testclient import TestClient

from apitool.web.app import create_app

HOST = "http://127.0.0.1:8000"


def _client(tmp_path):
    app = create_app(tmp_path / "data")
    return app, TestClient(app, base_url=HOST)


def _token(app):
    return app.state.csrf_token


# AC-40: demo jobs from the web UI
def test_fresh_app_shows_load_demo_jobs(tmp_path):
    _, client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Load demo jobs" in response.text


def test_setup_redirects_and_lists_five_demo_jobs(tmp_path):
    app, client = _client(tmp_path)
    response = client.post("/demo/setup", data={"csrf_token": _token(app)}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?notice=demo_loaded"

    page = client.get("/?notice=demo_loaded").text
    for name in [
        "Demo Orders",
        "Demo Customers",
        "Demo Events",
        "Demo Products",
        "Demo Flaky Orders",
    ]:
        assert name in page
    assert "Demo jobs are ready." in page


def test_setup_twice_still_five_jobs(tmp_path):
    app, client = _client(tmp_path)
    data = {"csrf_token": _token(app)}
    client.post("/demo/setup", data=data)
    client.post("/demo/setup", data=data)
    assert len(app.state.storage.list_jobs()) == 5


def test_dataset_switch_to_v2_is_saved_and_shown(tmp_path):
    app, client = _client(tmp_path)
    response = client.post(
        "/demo/dataset",
        data={"csrf_token": _token(app), "version": "2"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?notice=dataset_v2"
    assert app.state.storage.get_setting("demo_dataset_version", "1") == "2"
    page = client.get("/?notice=dataset_v2").text
    assert "dataset v2" in page


def test_dataset_version_three_is_bad_request(tmp_path):
    app, client = _client(tmp_path)
    response = client.post("/demo/dataset", data={"csrf_token": _token(app), "version": "3"})
    assert response.status_code == 400
    assert "Dataset version must be 1 or 2." in response.text


def test_notice_parameter_is_never_rendered(tmp_path):
    _, client = _client(tmp_path)
    response = client.get("/?notice=<script>alert(1)</script>")
    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "alert(1)" not in response.text


def test_demo_post_without_token_is_forbidden(tmp_path):
    _, client = _client(tmp_path)
    assert client.post("/demo/setup", data={}).status_code == 403
    assert client.post("/demo/setup", data={"csrf_token": "wrong"}).status_code == 403
    assert (
        client.post("/demo/dataset", data={"csrf_token": "wrong", "version": "1"}).status_code
        == 403
    )


# AC-41: job create, edit and delete forms. AC-36 (web half): state reset notices.
JOB_FORM = {
    "name": "Orders Test",
    "url": "https://api.example.com/v1/orders",
    "query_params": "",
    "headers": "",
    "timeout_seconds": "30",
    "auth_type": "api_key_header",
    "auth_key_name": "X-API-Key",
    "auth_username": "",
    "secret": "zz-secret-zz",
    "pagination_type": "page",
    "page_param": "page",
    "page_size_param": "per_page",
    "start_page": "1",
    "offset_param": "offset",
    "limit_param": "limit",
    "cursor_param": "cursor",
    "cursor_path": "",
    "next_url_path": "",
    "page_size": "4",
    "max_pages": "50",
    "records_path": "data",
    "fields": "",
    "renames": "",
    "dedup_key": "id",
    "export_format": "csv",
}


def _form(app, **changes):
    data = {**JOB_FORM, "csrf_token": app.state.csrf_token, **changes}
    return {key: value for key, value in data.items() if value is not None}


def _create(client, app, **changes):
    return client.post("/jobs", data=_form(app, **changes), follow_redirects=False)


def _job_id(app, name):
    return app.state.storage.get_job_by_name(name).id


def test_valid_create_stores_job_and_secret(tmp_path):
    app, client = _client(tmp_path)
    response = _create(client, app)
    assert response.status_code == 303
    assert response.headers["location"] == "/?notice=job_created"
    job_id = _job_id(app, "Orders Test")
    assert app.state.storage.get_secret(job_id) == "zz-secret-zz"


def test_invalid_url_is_400_with_entered_values_kept(tmp_path):
    app, client = _client(tmp_path)
    response = _create(client, app, url="ftp://api.example.com/x")
    assert response.status_code == 400
    assert "must start with http:// or https://" in response.text
    assert 'value="Orders Test"' in response.text
    assert app.state.storage.list_jobs() == []


def test_duplicate_name_is_400(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    response = _create(client, app, name="orders test")
    assert response.status_code == 400
    assert "a job with this name already exists" in response.text


def test_bearer_without_secret_on_create_is_400(tmp_path):
    app, client = _client(tmp_path)
    response = _create(client, app, auth_type="bearer", secret="")
    assert response.status_code == 400
    assert "required for this authentication type" in response.text


def test_secret_is_never_rendered_on_edit(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    page = client.get(f"/jobs/{job_id}/edit").text
    assert "zz-secret-zz" not in page
    assert "A secret is saved. Leave blank to keep it." in page


def test_blank_secret_on_edit_keeps_stored_secret(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    response = client.post(f"/jobs/{job_id}", data=_form(app, secret=""), follow_redirects=False)
    assert response.status_code == 303
    assert app.state.storage.get_secret(job_id) == "zz-secret-zz"


def test_clear_secret_with_auth_none_removes_it(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    response = client.post(
        f"/jobs/{job_id}",
        data=_form(app, secret="", clear_secret="on", auth_type="none"),
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert app.state.storage.get_secret(job_id) is None


def test_clearing_secret_for_bearer_without_new_one_is_400(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app, auth_type="bearer")
    job_id = _job_id(app, "Orders Test")
    response = client.post(
        f"/jobs/{job_id}",
        data=_form(app, secret="", clear_secret="on", auth_type="bearer"),
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "required for this authentication type" in response.text
    assert app.state.storage.get_secret(job_id) == "zz-secret-zz"


def test_failed_edit_does_not_change_secret(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    response = client.post(
        f"/jobs/{job_id}",
        data=_form(app, url="ftp://bad", secret="new-secret-value"),
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert app.state.storage.get_secret(job_id) == "zz-secret-zz"


def test_edit_url_change_reports_state_reset(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    response = client.post(
        f"/jobs/{job_id}",
        data=_form(app, url="https://api.example.com/v2/orders"),
        follow_redirects=False,
    )
    assert response.headers["location"] == "/?notice=state_reset_auto"


def test_edit_name_change_keeps_state(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    response = client.post(
        f"/jobs/{job_id}", data=_form(app, name="Renamed Orders"), follow_redirects=False
    )
    assert response.headers["location"] == "/?notice=job_updated"
    assert app.state.storage.get_job(job_id).name == "Renamed Orders"


def test_delete_removes_job(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    response = client.post(
        f"/jobs/{job_id}/delete",
        data={"csrf_token": app.state.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?notice=job_deleted"
    assert app.state.storage.get_job(job_id) is None


def test_reset_state_route(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app, incremental="on")
    job_id = _job_id(app, "Orders Test")
    response = client.post(
        f"/jobs/{job_id}/reset-state",
        data={"csrf_token": app.state.csrf_token},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/?notice=state_reset"


def test_unknown_job_id_is_404(tmp_path):
    _, client = _client(tmp_path)
    assert client.get("/jobs/999/edit").status_code == 404


# AC-39: every POST route that exists rejects a missing or wrong token
def test_every_post_route_needs_the_token(tmp_path):
    app, client = _client(tmp_path)
    _create(client, app)
    job_id = _job_id(app, "Orders Test")
    routes = [
        ("/jobs", dict(JOB_FORM)),
        (f"/jobs/{job_id}", dict(JOB_FORM)),
        (f"/jobs/{job_id}/delete", {}),
        (f"/jobs/{job_id}/reset-state", {}),
        ("/demo/setup", {}),
        ("/demo/dataset", {"version": "1"}),
    ]
    for path, data in routes:
        assert client.post(path, data=data).status_code == 403, path
        assert client.post(path, data={**data, "csrf_token": "wrong"}).status_code == 403, path
        ok = client.post(
            path, data={**data, "csrf_token": app.state.csrf_token}, follow_redirects=False
        )
        assert ok.status_code != 403, path
