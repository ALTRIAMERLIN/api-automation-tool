import httpx
import pytest

from apitool.config import build_job_config
from apitool.demo.api import DemoApi
from apitool.errors import HttpError, InvalidResponseError
from apitool.http_client import Fetcher, add_auth_query, build_headers, build_url

DEMO = "https://demo.api-automation-tool.local"


def _cfg(**overrides):
    base = {
        "name": "Test Job",
        "url": "https://api.example.com/v1/items",
        "pagination_type": "none",
    }
    return build_job_config({**base, **overrides})


def _demo_fetcher(api, cfg, secret, sleeps):
    return Fetcher(cfg, secret, httpx.MockTransport(api.handle), sleep=sleeps.append)


# AC-09: URL building
def test_build_url_matches_spec_example():
    cfg = _cfg(
        url="https://api.example.com/v1/items?a=1&b=2",
        query_params=[["b", "3"], ["c", "x y"]],
        auth_type="api_key_query",
        auth_key_name="key",
    )
    url = build_url(cfg, "s3cr&t", {"page": 1, "per_page": 50})
    assert url == ("https://api.example.com/v1/items?a=1&b=3&c=x+y&page=1&per_page=50&key=s3cr%26t")


def test_build_url_without_params_has_no_question_mark():
    cfg = _cfg()
    assert build_url(cfg, None, {}) == "https://api.example.com/v1/items"


# AC-10: auth headers
def test_api_key_header_auth():
    cfg = _cfg(auth_type="api_key_header", auth_key_name="X-API-Key")
    assert build_headers(cfg, "demo-key-123") == {"X-API-Key": "demo-key-123"}


def test_bearer_auth():
    cfg = _cfg(auth_type="bearer")
    assert build_headers(cfg, "demo-token-456") == {"Authorization": "Bearer demo-token-456"}


def test_basic_auth_encodes_username_and_secret():
    cfg = _cfg(auth_type="basic", auth_username="demo")
    assert build_headers(cfg, "demo-pass") == {"Authorization": "Basic ZGVtbzpkZW1vLXBhc3M="}


def test_auth_overwrites_same_named_custom_header_in_any_case():
    cfg = _cfg(
        auth_type="bearer",
        headers=[["Authorization", "custom"], ["authorization", "other"]],
    )
    headers = build_headers(cfg, "demo-token-456")
    assert headers == {"Authorization": "Bearer demo-token-456"}


def test_custom_header_duplicate_last_wins():
    cfg = _cfg(headers=[["X-A", "1"], ["X-A", "2"]])
    assert build_headers(cfg, None) == {"X-A": "2"}


def test_every_request_sends_user_agent_and_auth():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    cfg = _cfg(auth_type="bearer")
    with Fetcher(cfg, "demo-token-456", httpx.MockTransport(handler), sleep=lambda s: None) as f:
        f.get_json("https://api.example.com/v1/items")
    assert seen[0].headers["User-Agent"] == "api-automation-tool/1.0.0"
    assert seen[0].headers["Authorization"] == "Bearer demo-token-456"


# AC-09 (next_url follow-up): auth query is set or overwritten, rest unchanged
def test_add_auth_query_overwrites_existing_key_and_keeps_others():
    cfg = _cfg(auth_type="api_key_query", auth_key_name="api_key")
    url = "https://api.example.com/v1/items?page=2&api_key=old&x=y%20z"
    assert add_auth_query(url, cfg, "new") == (
        "https://api.example.com/v1/items?page=2&x=y%20z&api_key=new"
    )


def test_add_auth_query_does_nothing_for_other_auth_types():
    cfg = _cfg(auth_type="bearer")
    url = "https://api.example.com/v1/items?page=2"
    assert add_auth_query(url, cfg, "secret") == url


# AC-11: single-attempt response validation against the demo API
def test_not_json_body_is_invalid():
    api = DemoApi()
    sleeps = []
    cfg = _cfg(url=f"{DEMO}/v1/not-json")
    with _demo_fetcher(api, cfg, None, sleeps) as f:
        with pytest.raises(InvalidResponseError, match="not valid JSON") as exc_info:
            f.get_json(f"{DEMO}/v1/not-json")
    assert len(api.requests) == 1
    assert "?" not in str(exc_info.value)


def test_nan_body_is_rejected():
    api = DemoApi()
    cfg = _cfg(url=f"{DEMO}/v1/nan")
    with _demo_fetcher(api, cfg, None, []) as f:
        with pytest.raises(InvalidResponseError, match="not valid JSON"):
            f.get_json(f"{DEMO}/v1/nan")


def test_too_large_body_is_rejected():
    api = DemoApi()
    cfg = _cfg(url=f"{DEMO}/v1/too-large")
    with _demo_fetcher(api, cfg, None, []) as f:
        with pytest.raises(InvalidResponseError, match="response too large"):
            f.get_json(f"{DEMO}/v1/too-large")


def test_redirect_is_not_followed():
    api = DemoApi()
    sleeps = []
    cfg = _cfg(url=f"{DEMO}/v1/redirect")
    with _demo_fetcher(api, cfg, None, sleeps) as f:
        with pytest.raises(InvalidResponseError, match=r"unexpected redirect \(302\)"):
            f.get_json(f"{DEMO}/v1/redirect")
    assert len(api.requests) == 1
    assert sleeps == []


def test_wrong_key_is_http_401_without_retry():
    api = DemoApi()
    sleeps = []
    cfg = _cfg(
        url=f"{DEMO}/v1/orders",
        auth_type="api_key_header",
        auth_key_name="X-API-Key",
    )
    with _demo_fetcher(api, cfg, "wrong", sleeps) as f:
        with pytest.raises(HttpError, match="HTTP 401") as exc_info:
            f.get_json(f"{DEMO}/v1/orders")
    assert exc_info.value.status_code == 401
    assert len(api.requests) == 1
    assert sleeps == []


def test_unknown_path_is_http_404_without_retry():
    api = DemoApi()
    sleeps = []
    cfg = _cfg(url=f"{DEMO}/v1/nothing")
    with _demo_fetcher(api, cfg, None, sleeps) as f:
        with pytest.raises(HttpError, match="HTTP 404") as exc_info:
            f.get_json(f"{DEMO}/v1/nothing")
    assert len(api.requests) == 1
    assert "?" not in str(exc_info.value)


def test_successful_page_returns_decoded_json():
    api = DemoApi()
    cfg = _cfg(
        url=f"{DEMO}/v1/orders?page=1&per_page=4",
        auth_type="api_key_header",
        auth_key_name="X-API-Key",
    )
    with _demo_fetcher(api, cfg, "demo-key-123", []) as f:
        body = f.get_json(f"{DEMO}/v1/orders?page=1&per_page=4")
    assert len(body["data"]) == 4
    assert f.last_status == 200
