import logging

import httpx
import pytest

from apitool.config import build_job_config
from apitool.demo.api import DemoApi
from apitool.errors import HttpError, NetworkError
from apitool.http_client import Fetcher

DEMO = "https://demo.api-automation-tool.local"


def _cfg(**overrides):
    base = {
        "name": "Retry Job",
        "url": f"{DEMO}/v1/flaky-orders",
        "pagination_type": "none",
    }
    return build_job_config({**base, **overrides})


def _fetch(transport, url, cfg=None, secret=None):
    sleeps = []
    cfg = cfg or _cfg(url=url)
    f = Fetcher(cfg, secret, transport, sleep=sleeps.append)
    return f, sleeps


# AC-12: retry policy with the stub sleep


def test_flaky_orders_one_page_retries_once_after_zero_seconds():
    api = DemoApi()
    cfg = _cfg(
        url=f"{DEMO}/v1/flaky-orders?page=1&per_page=4",
        auth_type="api_key_header",
        auth_key_name="X-API-Key",
    )
    f, sleeps = _fetch(httpx.MockTransport(api.handle), cfg.url, cfg, "demo-key-123")
    with f:
        body = f.get_json(cfg.url)
    assert len(api.requests) == 2
    assert sleeps == [0]
    assert f.retries == 1
    assert f.last_status == 200
    assert len(body["data"]) == 4


def test_rate_limited_twice_then_ok_uses_retry_after_two():
    api = DemoApi()
    f, sleeps = _fetch(httpx.MockTransport(api.handle), f"{DEMO}/v1/rate-limited")
    with f:
        body = f.get_json(f"{DEMO}/v1/rate-limited")
    assert len(api.requests) == 3
    assert sleeps == [2, 2]
    assert f.retries == 2
    assert body == {"data": [{"id": 1}]}


def test_retry_after_is_capped_at_thirty_seconds():
    api = DemoApi()
    f, sleeps = _fetch(httpx.MockTransport(api.handle), f"{DEMO}/v1/retry-after-big")
    with f:
        f.get_json(f"{DEMO}/v1/retry-after-big")
    assert len(api.requests) == 2
    assert sleeps == [30]
    assert f.retries == 1


def test_always_500_gives_four_attempts_then_error():
    api = DemoApi()
    f, sleeps = _fetch(httpx.MockTransport(api.handle), f"{DEMO}/v1/always-500")
    with f:
        with pytest.raises(HttpError, match="HTTP 500") as exc_info:
            f.get_json(f"{DEMO}/v1/always-500")
    assert len(api.requests) == 4
    assert sleeps == [1, 2, 4]
    assert f.retries == 3
    assert exc_info.value.status_code == 500


def test_transport_error_every_time_gives_network_error():
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("boom")

    url = f"{DEMO}/v1/orders"
    f, sleeps = _fetch(httpx.MockTransport(handler), url)
    with f:
        with pytest.raises(NetworkError) as exc_info:
            f.get_json(url)
    assert len(attempts) == 4
    assert sleeps == [1, 2, 4]
    assert f.retries == 3
    # The message names the exception class only, never its text.
    assert "ConnectError" in str(exc_info.value)
    assert "boom" not in str(exc_info.value)


def test_503_with_bad_retry_after_uses_backoff_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "soon"})
        return httpx.Response(200, json={"data": []})

    f, sleeps = _fetch(httpx.MockTransport(handler), f"{DEMO}/v1/orders")
    with f:
        f.get_json(f"{DEMO}/v1/orders")
    assert len(calls) == 2
    assert sleeps == [1]
    assert f.retries == 1


def test_each_retry_is_logged_as_warning_without_query(caplog):
    api = DemoApi()
    url = f"{DEMO}/v1/rate-limited?secret=abc"
    f, _ = _fetch(httpx.MockTransport(api.handle), url)
    with caplog.at_level(logging.WARNING, logger="apitool"), f:
        f.get_json(url)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        f"retry 1/3 after 2 s: HTTP 429 ({DEMO}/v1/rate-limited)",
        f"retry 2/3 after 2 s: HTTP 429 ({DEMO}/v1/rate-limited)",
    ]
    assert "secret=abc" not in caplog.text
