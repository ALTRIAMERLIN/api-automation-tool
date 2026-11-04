"""Secret redaction, URL query stripping and the log filter (SPEC section 17)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

MASK = "***"
_LOGGER_NAME = "apitool"
# httpx logs every request URL at INFO, query string included. Those lines carry API keys that
# are passed in the query, so the httpx logger is filtered too and kept at WARNING.
_HTTPX_LOGGER_NAME = "httpx"

# Secrets registered for the current run. Every log record is scrubbed against this set.
_registered: set[str] = set()


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each non-empty secret with ``***``.

    Longer secrets are replaced first, so a secret that contains a shorter one is
    fully hidden.
    """
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return text


def strip_query(url: str) -> str:
    """Return the URL without query string, fragment and userinfo."""
    parts = urlsplit(url)
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def register_secrets(secrets: Iterable[str]) -> None:
    _registered.update(s for s in secrets if s)


def unregister_secrets(secrets: Iterable[str]) -> None:
    for secret in secrets:
        _registered.discard(secret)


class RedactingFilter(logging.Filter):
    """Scrub registered secrets from the message and the traceback of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), _registered)
        record.args = ()
        if record.exc_info:
            traceback_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact(traceback_text, _registered)
        return True


def install_filter() -> None:
    """Attach one RedactingFilter to the apitool and httpx loggers. Safe to call repeatedly."""
    for name in (_LOGGER_NAME, _HTTPX_LOGGER_NAME):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(RedactingFilter())
    logging.getLogger(_HTTPX_LOGGER_NAME).setLevel(logging.WARNING)
