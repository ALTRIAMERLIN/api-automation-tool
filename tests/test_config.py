import json

import pytest

from apitool.config import (
    JobConfig,
    build_job_config,
    format_fields,
    format_headers,
    format_query_params,
    format_renames,
    job_config_from_form,
    job_config_to_form,
    parse_fields,
    parse_headers,
    parse_query_params,
    parse_renames,
)
from apitool.errors import ConfigError

DEMO = "https://demo.api-automation-tool.local"

# A valid `page` pagination config. Every AC-03 case changes exactly one thing from it.
BASE = {
    "name": "Demo Orders",
    "url": "https://api.example.com/v1/orders",
    "pagination_type": "page",
    "page_size": 4,
    "records_path": "data",
}

# The five demo job configs from SPEC 19.3 (secrets are not part of the config).
DEMO_CONFIGS = [
    {
        "name": "Demo Orders",
        "url": f"{DEMO}/v1/orders",
        "auth_type": "api_key_header",
        "auth_key_name": "X-API-Key",
        "pagination_type": "page",
        "page_param": "page",
        "page_size_param": "per_page",
        "page_size": 4,
        "records_path": "data",
        "dedup_key": "id",
        "incremental": True,
        "export_format": "csv",
    },
    {
        "name": "Demo Customers",
        "url": f"{DEMO}/v1/customers",
        "auth_type": "bearer",
        "pagination_type": "offset",
        "offset_param": "offset",
        "limit_param": "limit",
        "page_size": 3,
        "records_path": "customers",
        "export_format": "xlsx",
    },
    {
        "name": "Demo Events",
        "url": f"{DEMO}/v1/events",
        "auth_type": "api_key_query",
        "auth_key_name": "api_key",
        "pagination_type": "cursor",
        "cursor_param": "cursor",
        "cursor_path": "next_cursor",
        "page_size_param": "limit",
        "page_size": 2,
        "records_path": "results",
        "dedup_key": "event_id",
        "export_format": "csv",
    },
    {
        "name": "Demo Products",
        "url": f"{DEMO}/v1/products",
        "auth_type": "basic",
        "auth_username": "demo",
        "pagination_type": "next_url",
        "next_url_path": "links.next",
        "records_path": "items",
        "fields": ["sku", "title", "price.amount", "price.currency", "stock"],
        "renames": [("price.amount", "price"), ("price.currency", "currency")],
        "export_format": "xlsx",
    },
    {
        "name": "Demo Flaky Orders",
        "url": f"{DEMO}/v1/flaky-orders",
        "auth_type": "api_key_header",
        "auth_key_name": "X-API-Key",
        "pagination_type": "page",
        "page_size": 4,
        "records_path": "data",
        "dedup_key": "id",
        "export_format": "csv",
    },
]


def _errors_for(data):
    with pytest.raises(ConfigError) as exc_info:
        build_job_config(data)
    return exc_info.value.errors


# AC-03: demo configs and the field-error table
@pytest.mark.parametrize("data", DEMO_CONFIGS, ids=lambda d: d["name"])
def test_demo_configs_build(data):
    cfg = build_job_config(data)
    assert isinstance(cfg, JobConfig)


def test_base_config_builds():
    assert build_job_config(BASE).name == "Demo Orders"


CASES = [
    ({"name": ""}, "name"),
    ({"name": "a/b"}, "name"),
    ({"name": "a" * 61}, "name"),
    ({"url": "ftp://x.example/a"}, "url"),
    ({"url": "https://user:pw@x.example/a"}, "url"),
    ({"url": "https://x.example/a#frag"}, "url"),
    ({"auth_type": "api_key_header", "auth_key_name": ""}, "auth_key_name"),
    ({"auth_type": "basic", "auth_username": ""}, "auth_username"),
    ({"page_size": 0}, "page_size"),
    ({"page_size": 1001}, "page_size"),
    ({"max_pages": 0}, "max_pages"),
    ({"max_pages": 1001}, "max_pages"),
    ({"timeout_seconds": 0}, "timeout_seconds"),
    ({"timeout_seconds": 121}, "timeout_seconds"),
    ({"incremental": True, "dedup_key": ""}, "incremental"),
    ({"pagination_type": "cursor", "cursor_path": ""}, "cursor_path"),
    ({"pagination_type": "next_url", "next_url_path": ""}, "next_url_path"),
    ({"export_format": "json"}, "export_format"),
    ({"records_path": "a..b"}, "records_path"),
]


@pytest.mark.parametrize(("change", "field"), CASES)
def test_invalid_config_reports_field(change, field):
    errors = _errors_for({**BASE, **change})
    assert any(name == field for name, _ in errors), errors


def test_name_is_stripped():
    assert build_job_config({**BASE, "name": "  Demo Orders  "}).name == "Demo Orders"


def test_name_length_error_message_has_no_secret_text():
    errors = _errors_for({**BASE, "name": "a" * 61})
    assert errors == [("name", "must be 1 to 60 characters")]


# AC-04: text parsers
def test_query_params_parse_skips_blank_and_splits_at_first_equals():
    assert parse_query_params("a=1\n\n b = x=y \n") == [("a", "1"), ("b", "x=y")]


def test_query_params_line_without_equals_is_error():
    with pytest.raises(ConfigError) as exc_info:
        parse_query_params("a=1\nbad")
    assert "line 2: expected key=value" in str(exc_info.value)


def test_headers_split_at_first_colon():
    assert parse_headers("X-Test: one: two") == [("X-Test", "one: two")]


def test_headers_line_without_colon_is_error():
    with pytest.raises(ConfigError) as exc_info:
        parse_headers("NoColon")
    assert "line 1: expected Name: value" in str(exc_info.value)


def test_fields_strip_and_drop_empty_items():
    assert parse_fields(" a, b ,,c ") == ["a", "b", "c"]


def test_fields_duplicate_is_error():
    with pytest.raises(ConfigError) as exc_info:
        parse_fields("a,a")
    assert "duplicate field 'a'" in str(exc_info.value)


def test_renames_blank_new_name_is_error():
    with pytest.raises(ConfigError) as exc_info:
        parse_renames("price.amount=price\nx=")
    assert exc_info.value.errors[0][0] == "renames"


def test_renames_old_name_twice_is_error():
    with pytest.raises(ConfigError):
        parse_renames("a=b\na=c")


@pytest.mark.parametrize(
    ("parse", "fmt", "value"),
    [
        (parse_query_params, format_query_params, [("a", "1"), ("b", "x=y")]),
        (parse_headers, format_headers, [("X-Test", "one: two")]),
        (parse_fields, format_fields, ["a", "b", "c"]),
        (parse_renames, format_renames, [("price.amount", "price")]),
    ],
)
def test_text_round_trip(parse, fmt, value):
    assert parse(fmt(value)) == value


def test_config_round_trips_through_json():
    cfg = build_job_config(DEMO_CONFIGS[3])
    restored = build_job_config(json.loads(cfg.model_dump_json()))
    assert restored == cfg


def test_form_round_trip():
    cfg = build_job_config(DEMO_CONFIGS[0])
    assert job_config_from_form(job_config_to_form(cfg)) == cfg


def test_form_blank_int_is_error():
    form = job_config_to_form(build_job_config(BASE))
    form["page_size"] = ""
    with pytest.raises(ConfigError) as exc_info:
        job_config_from_form(form)
    assert ("page_size", "must be a whole number") in exc_info.value.errors
