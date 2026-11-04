"""Page iterators for the five pagination styles (SPEC 8)."""

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from apitool.config import JobConfig
from apitool.errors import InvalidResponseError, PaginationError
from apitool.http_client import Fetcher, build_url
from apitool.jsonpath import MISSING, get_path
from apitool.redact import strip_query

_logger = logging.getLogger("apitool")
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass
class Progress:
    """Counters updated after every successful page."""

    pages_fetched: int = 0
    records_fetched: int = 0


@dataclass
class FetchResult:
    records: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    return "list"


def _records(body: Any, records_path: str) -> list[Any]:
    value = get_path(body, records_path)
    if value is MISSING:
        raise InvalidResponseError(f"records_path '{records_path}' not found in response")
    if not isinstance(value, list):
        raise InvalidResponseError(
            f"records_path '{records_path}' did not point to a list (got {_type_name(value)})"
        )
    return value


def _page_params(cfg: JobConfig, index: int, cursor: str | None) -> dict[str, str | int]:
    """Pagination query parameters for page ``index`` (0-based). Order matters for the URL."""
    style = cfg.pagination_type
    if style == "page":
        return {cfg.page_param: cfg.start_page + index, cfg.page_size_param: cfg.page_size}
    if style == "offset":
        return {cfg.offset_param: index * cfg.page_size, cfg.limit_param: cfg.page_size}
    if style == "cursor":
        params: dict[str, str | int] = {}
        if cursor is not None:
            params[cfg.cursor_param] = cursor
        if cfg.page_size_param.strip():
            params[cfg.page_size_param] = cfg.page_size
        return params
    return {}


def _origin(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) with the default port filled in. None when the URL is malformed."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if port is None:
        port = _DEFAULT_PORTS.get(scheme, -1)
    return (scheme, host, port)


def _log_page(url: str, number: int, status: int | None, count: int) -> None:
    _logger.info("GET %s page=%d status=%s records=%d", strip_query(url), number, status, count)


def fetch_all(cfg: JobConfig, fetcher: Fetcher, progress: Progress) -> FetchResult:
    """Fetch every page of the job and return all records and pagination warnings."""
    style = cfg.pagination_type
    max_pages = 1 if style == "none" else cfg.max_pages
    result = FetchResult()

    cursor: str | None = None
    used_cursors: set[str] = set()
    plain_url = build_url(cfg, None, {})
    requested: set[str] = {plain_url}
    current_plain = plain_url
    configured_origin = _origin(cfg.url)

    for index in range(max_pages):
        if style == "next_url":
            url = fetcher.follow_url(current_plain)
        else:
            url = fetcher.page_url(_page_params(cfg, index, cursor))
        body = fetcher.get_json(url)
        page_records = _records(body, cfg.records_path)
        _log_page(url, index + 1, fetcher.last_status, len(page_records))
        progress.pages_fetched += 1
        progress.records_fetched += len(page_records)
        result.records.extend(page_records)

        if style == "none":
            return result

        if style in ("page", "offset"):
            if len(page_records) < cfg.page_size:
                return result

        elif style == "cursor":
            next_value = get_path(body, cfg.cursor_path)
            if next_value is MISSING or next_value is None or next_value == "":
                return result
            if not page_records:
                return result
            if isinstance(next_value, bool) or not isinstance(next_value, str | int):
                raise InvalidResponseError(
                    f"cursor_path '{cfg.cursor_path}' must be a string or integer"
                )
            cursor = str(next_value)
            if cursor in used_cursors:
                raise PaginationError("cursor repeated: pagination loop detected")
            used_cursors.add(cursor)

        elif style == "next_url":
            next_value = get_path(body, cfg.next_url_path)
            if next_value is MISSING or next_value is None or next_value == "":
                return result
            if not page_records:
                return result
            if not isinstance(next_value, str):
                raise InvalidResponseError(f"next_url_path '{cfg.next_url_path}' must be a string")
            resolved = urljoin(current_plain, next_value)
            if _origin(resolved) != configured_origin:
                raise PaginationError(
                    "next URL points to a different host; refusing to send credentials"
                )
            if resolved in requested:
                raise PaginationError("next URL repeated: pagination loop detected")
            requested.add(resolved)
            current_plain = resolved

    result.warnings.append(
        f"max_pages_reached: stopped after {max_pages} pages; more data may exist"
    )
    return result


def fetch_first_page(cfg: JobConfig, fetcher: Fetcher) -> list[Any]:
    """Fetch only the first page and return its records (used by the preview)."""
    if cfg.pagination_type == "next_url":
        url = fetcher.follow_url(build_url(cfg, None, {}))
    else:
        url = fetcher.page_url(_page_params(cfg, 0, None))
    body = fetcher.get_json(url)
    return _records(body, cfg.records_path)
