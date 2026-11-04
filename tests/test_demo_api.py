import base64

import httpx
import pytest

from apitool.demo.api import DemoApi
from apitool.demo.data import ORDERS_V1, ORDERS_V2

DEMO = "https://demo.api-automation-tool.local"
KEY = {"X-API-Key": "demo-key-123"}
BEARER = {"Authorization": "Bearer demo-token-456"}
BASIC = {"Authorization": "Basic " + base64.b64encode(b"demo:demo-pass").decode()}


def _get(api, path, headers=None):
    client = httpx.Client(transport=httpx.MockTransport(api.handle))
    return client.get(f"{DEMO}{path}", headers=headers or {})


# AC-06: auth on each authed endpoint
@pytest.mark.parametrize(
    ("path", "right", "wrong_place"),
    [
        ("/v1/orders", KEY, BEARER),
        ("/v1/customers", BEARER, KEY),
        ("/v1/products", BASIC, BEARER),
    ],
)
def test_header_auth_endpoints(path, right, wrong_place):
    api = DemoApi()
    assert _get(api, path).status_code == 401
    assert _get(api, path, {"X-API-Key": "wrong"}).status_code == 401
    assert _get(api, path, wrong_place).status_code == 401
    assert _get(api, path, right).status_code == 200


def test_flaky_orders_auth_is_checked_before_flaky_503():
    api = DemoApi()
    assert _get(api, "/v1/flaky-orders", BEARER).status_code == 401
    assert _get(api, "/v1/flaky-orders", {"X-API-Key": "wrong"}).status_code == 401
    # The first correctly authenticated request for page 1 is the flaky 503.
    assert _get(api, "/v1/flaky-orders?page=1", KEY).status_code == 503


def test_events_auth_is_query_key():
    api = DemoApi()
    assert _get(api, "/v1/events").status_code == 401
    assert _get(api, "/v1/events?api_key=wrong").status_code == 401
    assert _get(api, "/v1/events?api_key=demo-key-123").status_code == 200


def test_unknown_path_is_404():
    assert _get(DemoApi(), "/v1/nope").status_code == 404


def test_bad_parameters_are_400():
    api = DemoApi()
    assert _get(api, "/v1/orders?per_page=0", KEY).status_code == 400
    assert _get(api, "/v1/events?cursor=zzz&api_key=demo-key-123").status_code == 400
    assert _get(api, "/v1/products?page=4", BASIC).status_code == 400


# AC-07: response shapes
def test_orders_page_three_of_four_v1():
    response = _get(DemoApi(1), "/v1/orders?page=3&per_page=4", KEY)
    body = response.json()
    assert [r["id"] for r in body["data"]] == [1002, 1007, 1008]
    assert body["meta"]["total"] == 11


def test_orders_v2_total_is_14():
    body = _get(DemoApi(2), "/v1/orders?page=4&per_page=4", KEY).json()
    assert body["meta"]["total"] == 14
    assert len(body["data"]) == 2


def test_orders_datasets_have_expected_sizes():
    assert len(ORDERS_V1) == 11
    assert len(ORDERS_V2) == 14


def test_customers_offset_past_end_is_empty():
    body = _get(DemoApi(), "/v1/customers?offset=6&limit=3", BEARER).json()
    assert body["customers"] == []


def test_products_page_two_links_to_page_three():
    body = _get(DemoApi(), "/v1/products?page=2", BASIC).json()
    assert body["links"]["next"] == "/v1/products?page=3"


def test_flaky_orders_first_call_503_then_200():
    api = DemoApi()
    first = _get(api, "/v1/flaky-orders?page=1", KEY)
    second = _get(api, "/v1/flaky-orders?page=1", KEY)
    assert first.status_code == 503
    assert first.headers["Retry-After"] == "0"
    assert second.status_code == 200


def test_requests_are_recorded():
    api = DemoApi()
    _get(api, "/v1/nope")
    _get(api, "/v1/orders?page=1", KEY)
    assert len(api.requests) == 2


def test_events_cursor_pages_and_absent_cursor():
    api = DemoApi()
    first = _get(api, "/v1/events?api_key=demo-key-123").json()
    assert first["next_cursor"] == "c_2"
    assert [r["event_id"] for r in first["results"]] == ["evt_001", "evt_002"]
    last = _get(api, "/v1/events?cursor=c_4&api_key=demo-key-123").json()
    assert last["next_cursor"] is None


def test_rate_limited_first_two_calls_429():
    api = DemoApi()
    assert _get(api, "/v1/rate-limited").status_code == 429
    assert _get(api, "/v1/rate-limited").headers["Retry-After"] == "2"
    assert _get(api, "/v1/rate-limited").status_code == 200


def test_redirect_and_nan_and_too_large_bodies():
    api = DemoApi()
    assert _get(api, "/v1/redirect").status_code == 302
    assert b"NaN" in _get(api, "/v1/nan").content
    assert len(_get(api, "/v1/too-large").content) == 10 * 1024 * 1024 + 1
