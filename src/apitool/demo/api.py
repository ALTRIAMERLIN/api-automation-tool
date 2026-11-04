"""In-process fake REST API for demo mode, served through an httpx MockTransport (SPEC 19)."""

import re
from typing import Any

import httpx

from apitool.demo.data import CUSTOMERS, EVENTS_PAGES, ORDERS_V1, ORDERS_V2, PRODUCTS_PAGES

# Public demo credential for the built-in fake API. Not a secret.
# DEMO_BASIC_AUTH is base64 of demo:demo-pass.
DEMO_API_KEY = "demo-key-123"
DEMO_BEARER_TOKEN = "demo-token-456"
DEMO_BASIC_AUTH = "Basic ZGVtbzpkZW1vLXBhc3M="

_INT_RE = re.compile(r"-?\d+")
_MAX_BODY_BYTES = 10 * 1024 * 1024 + 1
_CURSOR_PAGES = {None: 0, "c_2": 1, "c_4": 2}


class _BadRequest(Exception):
    pass


def _int_param(params: httpx.QueryParams, name: str, default: int, low: int, high: int) -> int:
    raw = params.get(name)
    if raw is None:
        return default
    if not _INT_RE.fullmatch(raw):
        raise _BadRequest
    value = int(raw)
    if not low <= value <= high:
        raise _BadRequest
    return value


def _json(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


class DemoApi:
    """Serves the demo endpoints. Per-instance counters make the retry demos repeatable."""

    def __init__(self, dataset_version: int = 1) -> None:
        if dataset_version not in (1, 2):
            raise ValueError("dataset_version must be 1 or 2")
        self._orders = ORDERS_V2 if dataset_version == 2 else ORDERS_V1
        self._flaky_pages_seen: set[int] = set()
        self._rate_limited_calls = 0
        self._retry_after_big_calls = 0
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        try:
            return self._route(request)
        except _BadRequest:
            return _json(400, {"error": "bad request"})

    def _route(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = request.url.params
        headers = request.headers

        if path == "/v1/orders":
            if headers.get("X-API-Key") != DEMO_API_KEY:
                return _json(401, {"error": "unauthorized"})
            return _orders_page(self._orders, params)

        if path == "/v1/flaky-orders":
            if headers.get("X-API-Key") != DEMO_API_KEY:
                return _json(401, {"error": "unauthorized"})
            page = _int_param(params, "page", 1, 1, 1_000_000)
            if page not in self._flaky_pages_seen:
                self._flaky_pages_seen.add(page)
                return _json(503, {"error": "temporarily unavailable"}, {"Retry-After": "0"})
            return _orders_page(self._orders, params)

        if path == "/v1/customers":
            if headers.get("Authorization") != f"Bearer {DEMO_BEARER_TOKEN}":
                return _json(401, {"error": "unauthorized"})
            offset = _int_param(params, "offset", 0, 0, 1_000_000_000)
            limit = _int_param(params, "limit", 3, 1, 100)
            return _json(
                200,
                {"customers": CUSTOMERS[offset : offset + limit], "total": len(CUSTOMERS)},
            )

        if path == "/v1/events":
            if params.get("api_key") != DEMO_API_KEY:
                return _json(401, {"error": "unauthorized"})
            cursor = params.get("cursor")
            if cursor not in _CURSOR_PAGES:
                return _json(400, {"error": "bad request"})
            page = EVENTS_PAGES[_CURSOR_PAGES[cursor]]
            return _json(200, {"results": page["results"], "next_cursor": page["next_cursor"]})

        if path == "/v1/products":
            if headers.get("Authorization") != DEMO_BASIC_AUTH:
                return _json(401, {"error": "unauthorized"})
            page = _int_param(params, "page", 1, 1, 3)
            data = PRODUCTS_PAGES[page - 1]
            return _json(200, {"items": data["items"], "links": data["links"]})

        if path == "/v1/always-500":
            return _json(500, {"error": "server error"})

        if path == "/v1/rate-limited":
            self._rate_limited_calls += 1
            if self._rate_limited_calls <= 2:
                return _json(429, {"error": "rate limited"}, {"Retry-After": "2"})
            return _json(200, {"data": [{"id": 1}]})

        if path == "/v1/retry-after-big":
            self._retry_after_big_calls += 1
            if self._retry_after_big_calls == 1:
                return _json(503, {"error": "temporarily unavailable"}, {"Retry-After": "120"})
            return _json(200, {"data": [{"id": 1}]})

        if path == "/v1/not-json":
            return httpx.Response(
                200, content=b"<html>oops</html>", headers={"Content-Type": "text/html"}
            )

        if path == "/v1/nan":
            return httpx.Response(
                200,
                content=b'{"data": [{"v": NaN}]}',
                headers={"Content-Type": "application/json"},
            )

        if path == "/v1/loop-cursor":
            return _json(200, {"results": [{"id": 1}], "next_cursor": "same"})

        if path == "/v1/offsite-next":
            return _json(
                200,
                {"items": [{"id": 1}], "links": {"next": "https://evil.example/steal"}},
            )

        if path == "/v1/object-records":
            return _json(200, {"data": {"id": 1}})

        if path == "/v1/redirect":
            return httpx.Response(302, headers={"Location": "/v1/orders"})

        if path == "/v1/too-large":
            return httpx.Response(
                200,
                content=b" " * _MAX_BODY_BYTES,
                headers={"Content-Type": "application/json"},
            )

        return _json(404, {"error": "not found"})


def _orders_page(self_orders: list[dict[str, Any]], params: httpx.QueryParams) -> httpx.Response:
    page = _int_param(params, "page", 1, 1, 1_000_000)
    per_page = _int_param(params, "per_page", 4, 1, 100)
    start = (page - 1) * per_page
    body = {
        "data": self_orders[start : start + per_page],
        "meta": {"page": page, "per_page": per_page, "total": len(self_orders)},
    }
    return _json(200, body)
