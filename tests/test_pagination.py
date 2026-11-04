import httpx
import pytest

from apitool.config import build_job_config
from apitool.demo.api import DemoApi
from apitool.errors import InvalidResponseError, PaginationError
from apitool.http_client import Fetcher
from apitool.pagination import Progress, fetch_all, fetch_first_page

DEMO = "https://demo.api-automation-tool.local"


def _cfg(**overrides):
    base = {"name": "Pager", "url": f"{DEMO}/v1/x", "pagination_type": "none"}
    return build_job_config({**base, **overrides})


def _run(api, cfg, secret=None):
    sleeps = []
    fetcher = Fetcher(cfg, secret, httpx.MockTransport(api.handle), sleep=sleeps.append)
    progress = Progress()
    with fetcher:
        result = fetch_all(cfg, fetcher, progress)
    return result, progress, sleeps


def _urls(api):
    return [str(r.url) for r in api.requests]


ORDERS_KEY = {
    "url": f"{DEMO}/v1/orders",
    "auth_type": "api_key_header",
    "auth_key_name": "X-API-Key",
    "pagination_type": "page",
    "page_size": 4,
    "records_path": "data",
}
ORDERS_SECRET = "demo-key-123"


# AC-13: exact request URLs, in order
def test_orders_pages_of_four_v1():
    api = DemoApi(1)
    cfg = _cfg(**ORDERS_KEY)
    result, progress, _ = _run(api, cfg, ORDERS_SECRET)
    assert _urls(api) == [
        f"{DEMO}/v1/orders?page=1&per_page=4",
        f"{DEMO}/v1/orders?page=2&per_page=4",
        f"{DEMO}/v1/orders?page=3&per_page=4",
    ]
    assert len(result.records) == 11
    assert result.warnings == []
    assert (progress.pages_fetched, progress.records_fetched) == (3, 11)


def test_orders_page_size_eleven_needs_empty_second_page():
    api = DemoApi(1)
    cfg = _cfg(**{**ORDERS_KEY, "page_size": 11})
    _run(api, cfg, ORDERS_SECRET)
    assert _urls(api) == [
        f"{DEMO}/v1/orders?page=1&per_page=11",
        f"{DEMO}/v1/orders?page=2&per_page=11",
    ]


def test_customers_offset_stops_on_empty_page():
    api = DemoApi()
    cfg = _cfg(
        url=f"{DEMO}/v1/customers",
        auth_type="bearer",
        pagination_type="offset",
        page_size=3,
        records_path="customers",
    )
    result, _, _ = _run(api, cfg, "demo-token-456")
    assert _urls(api) == [
        f"{DEMO}/v1/customers?offset=0&limit=3",
        f"{DEMO}/v1/customers?offset=3&limit=3",
        f"{DEMO}/v1/customers?offset=6&limit=3",
    ]
    assert len(result.records) == 6


def test_events_cursor_with_query_key():
    api = DemoApi()
    cfg = _cfg(
        url=f"{DEMO}/v1/events",
        auth_type="api_key_query",
        auth_key_name="api_key",
        pagination_type="cursor",
        cursor_param="cursor",
        cursor_path="next_cursor",
        page_size_param="limit",
        page_size=2,
        records_path="results",
    )
    result, _, _ = _run(api, cfg, "demo-key-123")
    assert _urls(api) == [
        f"{DEMO}/v1/events?limit=2&api_key=demo-key-123",
        f"{DEMO}/v1/events?cursor=c_2&limit=2&api_key=demo-key-123",
        f"{DEMO}/v1/events?cursor=c_4&limit=2&api_key=demo-key-123",
    ]
    assert len(result.records) == 6


def test_products_next_url_absolute_then_relative():
    api = DemoApi()
    cfg = _cfg(
        url=f"{DEMO}/v1/products",
        auth_type="basic",
        auth_username="demo",
        pagination_type="next_url",
        next_url_path="links.next",
        records_path="items",
    )
    result, _, _ = _run(api, cfg, "demo-pass")
    assert _urls(api) == [
        f"{DEMO}/v1/products",
        f"{DEMO}/v1/products?page=2",
        f"{DEMO}/v1/products?page=3",
    ]
    assert len(result.records) == 5


def test_none_pagination_fetches_one_page_with_retry():
    api = DemoApi()
    cfg = _cfg(url=f"{DEMO}/v1/rate-limited", records_path="data")
    result, progress, sleeps = _run(api, cfg)
    assert (progress.pages_fetched, len(result.records)) == (1, 1)
    assert sleeps == [2, 2]


# AC-14: loops, host checks and records_path errors
def test_cursor_loop_is_detected_after_two_requests():
    api = DemoApi()
    cfg = _cfg(
        url=f"{DEMO}/v1/loop-cursor",
        pagination_type="cursor",
        cursor_path="next_cursor",
        records_path="results",
    )
    with pytest.raises(PaginationError, match="pagination loop detected"):
        _run(api, cfg)
    assert len(api.requests) == 2


def test_next_url_to_other_host_is_refused_before_sending():
    api = DemoApi()
    cfg = _cfg(
        url=f"{DEMO}/v1/offsite-next",
        pagination_type="next_url",
        next_url_path="links.next",
        records_path="items",
    )
    with pytest.raises(PaginationError, match="different host"):
        _run(api, cfg)
    assert len(api.requests) == 1
    assert all(r.url.host == "demo.api-automation-tool.local" for r in api.requests)


def test_object_records_path_is_invalid_list():
    cfg = _cfg(url=f"{DEMO}/v1/object-records", records_path="data")
    with pytest.raises(InvalidResponseError, match=r"did not point to a list \(got object\)"):
        _run(DemoApi(), cfg)


def test_missing_records_path_is_invalid():
    cfg = _cfg(**{**ORDERS_KEY, "records_path": "items"})
    with pytest.raises(InvalidResponseError, match="records_path 'items' not found"):
        _run(DemoApi(1), cfg, ORDERS_SECRET)


# AC-15: max_pages
def test_max_pages_two_adds_warning():
    api = DemoApi(1)
    cfg = _cfg(**{**ORDERS_KEY, "max_pages": 2})
    result, _, _ = _run(api, cfg, ORDERS_SECRET)
    assert len(api.requests) == 2
    assert len(result.records) == 8
    assert result.warnings == ["max_pages_reached: stopped after 2 pages; more data may exist"]


def test_max_pages_three_has_no_warning():
    api = DemoApi(1)
    cfg = _cfg(**{**ORDERS_KEY, "max_pages": 3})
    result, _, _ = _run(api, cfg, ORDERS_SECRET)
    assert len(api.requests) == 3
    assert result.warnings == []


def test_first_page_only_for_preview():
    api = DemoApi(1)
    cfg = _cfg(**ORDERS_KEY)
    sleeps = []
    with Fetcher(cfg, ORDERS_SECRET, httpx.MockTransport(api.handle), sleep=sleeps.append) as f:
        records = fetch_first_page(cfg, f)
    assert len(records) == 4
    assert len(api.requests) == 1
