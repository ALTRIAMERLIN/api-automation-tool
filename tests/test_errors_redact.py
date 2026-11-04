import logging

import pytest

from apitool import redact as redact_mod
from apitool.errors import (
    AppError,
    ConfigError,
    ExportError,
    HttpError,
    InvalidResponseError,
    JobBusyError,
    JobNotFoundError,
    NetworkError,
    PaginationError,
    TransformError,
)
from apitool.redact import (
    RedactingFilter,
    install_filter,
    redact,
    register_secrets,
    strip_query,
    unregister_secrets,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    # Start and finish every test with no registered secrets.
    redact_mod._registered.clear()
    yield
    redact_mod._registered.clear()


# AC-02: exit codes
def test_exit_codes_usage_errors_are_2():
    assert ConfigError([("name", "bad")]).exit_code == 2
    assert JobNotFoundError("missing").exit_code == 2
    assert JobBusyError("busy").exit_code == 2


def test_exit_codes_run_errors_are_1():
    assert HttpError("HTTP 500", 500).exit_code == 1
    assert NetworkError("net").exit_code == 1
    assert InvalidResponseError("bad").exit_code == 1
    assert PaginationError("loop").exit_code == 1
    assert TransformError("dup").exit_code == 1
    assert ExportError("io").exit_code == 1


def test_base_app_error_is_1_and_str_is_message():
    err = AppError("boom")
    assert err.exit_code == 1
    assert str(err) == "boom"


def test_config_error_message_joins_field_pairs():
    err = ConfigError([("name", "required"), ("url", "bad scheme")])
    assert err.errors == [("name", "required"), ("url", "bad scheme")]
    assert str(err) == "name: required; url: bad scheme"


def test_http_error_keeps_status_code():
    err = HttpError("HTTP 401 from https://x.example/a", 401)
    assert err.status_code == 401
    assert str(err) == "HTTP 401 from https://x.example/a"


# AC-02: redaction
def test_redact_longer_secret_first():
    assert redact("token abc and abcdef", ["abc", "abcdef"]) == "token *** and ***"


def test_redact_ignores_empty_secret():
    assert redact("x", [""]) == "x"


def test_strip_query_keeps_scheme_host_port_path():
    assert strip_query("https://h.example:8443/a/b?api_key=s&x=1") == "https://h.example:8443/a/b"


def test_strip_query_removes_fragment_and_userinfo():
    assert strip_query("https://u:p@h.example/a#frag") == "https://h.example/a"


def test_redacting_filter_scrubs_registered_secret(caplog):
    install_filter()
    register_secrets(["s3cr3t"])
    logger = logging.getLogger("apitool")
    with caplog.at_level(logging.DEBUG, logger="apitool"):
        logger.info("value=%s", "s3cr3t")
    assert "value=***" in caplog.text
    assert "s3cr3t" not in caplog.text


def test_redacting_filter_after_unregister_logs_plain(caplog):
    install_filter()
    register_secrets(["s3cr3t"])
    unregister_secrets(["s3cr3t"])
    logger = logging.getLogger("apitool")
    with caplog.at_level(logging.DEBUG, logger="apitool"):
        logger.info("value=%s", "s3cr3t")
    assert "value=s3cr3t" in caplog.text


def test_install_filter_is_idempotent():
    install_filter()
    install_filter()
    logger = logging.getLogger("apitool")
    count = sum(isinstance(f, RedactingFilter) for f in logger.filters)
    assert count == 1


def test_traceback_text_is_redacted(caplog):
    install_filter()
    register_secrets(["tb-secret-42"])
    logger = logging.getLogger("apitool")
    with caplog.at_level(logging.ERROR, logger="apitool"):
        try:
            raise ValueError("bad value tb-secret-42")
        except ValueError:
            logger.error("failed", exc_info=True)
    assert "ValueError" in caplog.text  # the traceback is still logged
    assert "bad value ***" in caplog.text
    assert "tb-secret-42" not in caplog.text


def test_httpx_logger_is_filtered_and_quiet():
    install_filter()
    httpx_logger = logging.getLogger("httpx")
    assert any(isinstance(f, RedactingFilter) for f in httpx_logger.filters)
    assert httpx_logger.level == logging.WARNING
    assert httpx_logger.isEnabledFor(logging.INFO) is False


def test_httpx_warning_with_secret_in_url_is_redacted(caplog):
    install_filter()
    register_secrets(["query-key-9"])
    with caplog.at_level(logging.WARNING):
        logging.getLogger("httpx").warning("slow request ?api_key=query-key-9")
    assert "api_key=***" in caplog.text
    assert "query-key-9" not in caplog.text
