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
