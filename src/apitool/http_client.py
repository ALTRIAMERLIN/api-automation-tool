"""HTTP requests for one job: URL building, headers, auth, response checks and retries (SPEC 6)."""

import base64
import json
import logging
import re
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any
from urllib.parse import parse_qsl, quote_plus, unquote_plus, urlencode, urlsplit, urlunsplit

import httpx

from apitool.config import JobConfig
from apitool.errors import HttpError, InvalidResponseError, NetworkError
from apitool.redact import strip_query

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
BACKOFF = (1, 2, 4)
MAX_RETRY_AFTER = 30
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "api-automation-tool/1.0.0"

_logger = logging.getLogger("apitool")
_DIGITS_RE = re.compile(r"[0-9]+")


def build_url(cfg: JobConfig, secret: str | None, page_params: Mapping[str, str | int]) -> str:
    """Build the request URL (SPEC 6.2). The query is rebuilt with urlencode, never params=."""
    parts = urlsplit(cfg.url)
    params: dict[str, str] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        params[key] = value
    for key, value in cfg.query_params:
        params[key] = value
    for key, value in page_params.items():
        params[key] = str(value)
    if cfg.auth_type == "api_key_query" and secret is not None:
        params[cfg.auth_key_name] = secret
    query = urlencode(list(params.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def add_auth_query(url: str, cfg: JobConfig, secret: str | None) -> str:
    """Set the api_key_query parameter on a next_url follow-up URL (SPEC 8.5).

    Every other part of the URL stays exactly as given.
    """
    if cfg.auth_type != "api_key_query" or secret is None:
        return url
    parts = urlsplit(url)
    key = cfg.auth_key_name
    kept: list[str] = []
    if parts.query:
        for segment in parts.query.split("&"):
            name = unquote_plus(segment.split("=", 1)[0])
            if segment and name != key:
                kept.append(segment)
    kept.append(f"{quote_plus(key)}={quote_plus(secret)}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), parts.fragment))


def _set_header(headers: dict[str, str], name: str, value: str) -> None:
    """Set a header, replacing any existing header with the same name in any letter case."""
    lowered = name.lower()
    for existing in [key for key in headers if key.lower() == lowered]:
        del headers[existing]
    headers[name] = value


def build_headers(cfg: JobConfig, secret: str | None) -> dict[str, str]:
    """Custom headers, then auth. Auth always wins over a same-named custom header (SPEC 6.3)."""
    headers: dict[str, str] = {}
    for name, value in cfg.headers:
        _set_header(headers, name, value)
    if secret is None:
        return headers
    if cfg.auth_type == "api_key_header":
        _set_header(headers, cfg.auth_key_name, secret)
    elif cfg.auth_type == "bearer":
        _set_header(headers, "Authorization", f"Bearer {secret}")
    elif cfg.auth_type == "basic":
        token = base64.b64encode(f"{cfg.auth_username}:{secret}".encode()).decode("ascii")
        _set_header(headers, "Authorization", f"Basic {token}")
    return headers


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def _retry_delay(response: httpx.Response, backoff_index: int) -> int:
    value = response.headers.get("Retry-After")
    if value is not None and _DIGITS_RE.fullmatch(value.strip()):
        return min(int(value.strip()), MAX_RETRY_AFTER)
    return BACKOFF[backoff_index]


def _decode(response: httpx.Response, shown: str) -> Any:
    body = response.content
    if len(body) > MAX_RESPONSE_BYTES:
        raise InvalidResponseError(f"response too large (> 10 MiB) from {shown}")
    try:
        return json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
    except ValueError:
        raise InvalidResponseError(f"response is not valid JSON from {shown}") from None


class Fetcher:
    """Fetches JSON pages for one job over one httpx client (SPEC 6.1)."""

    def __init__(
        self,
        cfg: JobConfig,
        secret: str | None,
        transport: httpx.BaseTransport,
        sleep: Callable[[float], None],
    ) -> None:
        self._cfg = cfg
        self._secret = secret
        self._headers = build_headers(cfg, secret)
        self._sleep = sleep
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(cfg.timeout_seconds),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self.retries = 0
        self.last_status: int | None = None

    def page_url(self, page_params: Mapping[str, str | int]) -> str:
        """Request URL for one page, with the pagination parameters and auth applied."""
        return build_url(self._cfg, self._secret, page_params)

    def follow_url(self, url: str) -> str:
        """Request URL for a next_url follow-up: only the auth query parameter is added."""
        return add_auth_query(url, self._cfg, self._secret)

    def get_json(self, url: str) -> Any:
        """GET one page and return its decoded JSON. Retries follow SPEC 6.4 and 6.5."""
        shown = strip_query(url)
        retries_here = 0
        while True:
            try:
                response = self._client.get(url, headers=self._headers)
            except httpx.TransportError as exc:
                self.last_status = None
                reason = type(exc).__name__
                if retries_here >= len(BACKOFF):
                    raise NetworkError(f"network error ({reason}) from {shown}") from None
                delay: float = BACKOFF[retries_here]
            else:
                status = response.status_code
                self.last_status = status
                if 300 <= status <= 399:
                    raise InvalidResponseError(f"unexpected redirect ({status}) from {shown}")
                if status in RETRYABLE_STATUSES:
                    reason = f"HTTP {status}"
                    if retries_here >= len(BACKOFF):
                        raise HttpError(f"{reason} from {shown}", status)
                    delay = _retry_delay(response, retries_here)
                elif not 200 <= status <= 299:
                    raise HttpError(f"HTTP {status} from {shown}", status)
                else:
                    return _decode(response, shown)

            retries_here += 1
            self.retries += 1
            _logger.warning(
                "retry %d/%d after %s s: %s (%s)",
                retries_here,
                len(BACKOFF),
                delay,
                reason,
                shown,
            )
            self._sleep(delay)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
