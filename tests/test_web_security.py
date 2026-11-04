import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apitool.web.app import create_app

TEMPLATES = Path(__file__).parent.parent / "src" / "apitool" / "web" / "templates"

EXPECTED_HEADERS = {
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "data")


def _client(app, host="http://127.0.0.1:8000"):
    return TestClient(app, base_url=host)


def _assert_security_headers(response):
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers[name] == value, name


# AC-38: host check, security headers, no inline script or style
def test_evil_host_is_rejected_as_plain_text(app):
    response = _client(app, "http://evil.example").get("/healthz")
    assert response.status_code == 400
    assert response.text == "invalid host"
    _assert_security_headers(response)


def test_evil_host_on_root_is_rejected_before_routing(app):
    response = _client(app, "http://evil.example").get("/")
    assert response.status_code == 400
    assert response.text == "invalid host"


def test_localhost_with_port_is_allowed(app):
    response = _client(app, "http://localhost:8000").get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    _assert_security_headers(response)


def test_security_headers_on_success_and_not_found(app):
    client = _client(app)
    ok = client.get("/healthz")
    missing = client.get("/no-such-page")
    assert ok.status_code == 200
    assert missing.status_code == 404
    _assert_security_headers(ok)
    _assert_security_headers(missing)


def test_not_found_page_uses_spec_text(app):
    response = _client(app).get("/no-such-page")
    assert "Not found." in response.text
    assert "text/html" in response.headers["content-type"]


def test_templates_have_no_inline_script_or_style():
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", text)
        assert inline_scripts == [], path.name
        assert " style=" not in text, path.name


def test_static_files_are_served(app):
    response = _client(app).get("/static/style.css")
    assert response.status_code == 200


# AC-39 (helper part): the CSRF check rejects a missing or wrong token
def test_check_csrf_rejects_missing_and_wrong_tokens(app):
    check = app.state.check_csrf
    with pytest.raises(HTTPException) as missing:
        check(None)
    assert missing.value.status_code == 403
    with pytest.raises(HTTPException) as wrong:
        check("not-the-token")
    assert wrong.value.status_code == 403
    with pytest.raises(HTTPException) as non_ascii:
        check("zzé")
    assert non_ascii.value.status_code == 403


def test_check_csrf_accepts_the_process_token(app):
    app.state.check_csrf(app.state.csrf_token)


def test_csrf_token_is_random_per_app(tmp_path):
    first = create_app(tmp_path / "a").state.csrf_token
    second = create_app(tmp_path / "b").state.csrf_token
    assert first != second
    assert len(first) >= 40
