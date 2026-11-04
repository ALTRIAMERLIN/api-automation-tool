import json
from pathlib import Path

import pytest

from apitool.config import build_job_config
from apitool.demo.data import ORDERS_V1, ORDERS_V2, PRODUCTS_PAGES
from apitool.errors import TransformError
from apitool.pipeline import build_rows
from apitool.transform import csv_cell, sanitize_text

EXPECTED = Path(__file__).parent / "fixtures" / "expected"


def _fixture(name):
    return json.loads((EXPECTED / name).read_text(encoding="utf-8"))


def _cfg(**overrides):
    base = {"name": "Pipe", "url": "https://api.example.com/v1/x", "pagination_type": "none"}
    return build_job_config({**base, **overrides})


def _csv_view(result):
    header = [sanitize_text(h) for h in result.header]
    rows = [[csv_cell(v) for v in row] for row in result.rows]
    return [header, *rows]


def _assert_invariant(result, fetched):
    assert fetched == (
        result.records_missing_key
        + result.duplicates_removed
        + result.already_seen_skipped
        + result.records_exported
    )


# AC-18: Demo Orders v1, dedup on id
def test_orders_with_dedup_match_fixture():
    cfg = _cfg(dedup_key="id")
    result = build_rows(ORDERS_V1, cfg, set())
    assert _csv_view(result) == _fixture("orders_dedup_rows.json")
    assert (
        len(ORDERS_V1),
        result.duplicates_removed,
        result.records_missing_key,
        result.already_seen_skipped,
        result.records_exported,
    ) == (11, 2, 1, 0, 8)
    assert result.warnings == [
        "missing_key: 1 records skipped because key field 'id' was missing or empty"
    ]
    _assert_invariant(result, len(ORDERS_V1))


# AC-19: Demo Orders v1, no dedup
def test_orders_without_dedup_match_fixture():
    cfg = _cfg()
    result = build_rows(ORDERS_V1, cfg, set())
    assert _csv_view(result) == _fixture("orders_nodedup_rows.json")
    assert (
        result.duplicates_removed,
        result.records_missing_key,
        result.already_seen_skipped,
        result.records_exported,
    ) == (0, 0, 0, 11)
    assert result.warnings == []


# AC-20: Demo Products with field selection and renames
PRODUCT_FIELDS = ["sku", "title", "price.amount", "price.currency", "stock"]
PRODUCT_RENAMES = [["price.amount", "price"], ["price.currency", "currency"]]


def _products():
    return [item for page in PRODUCTS_PAGES for item in page["items"]]


def test_products_fields_and_renames():
    cfg = _cfg(fields=PRODUCT_FIELDS, renames=PRODUCT_RENAMES)
    result = build_rows(_products(), cfg, set())
    assert result.header == ["sku", "title", "price", "currency", "stock"]
    view = _csv_view(result)
    assert view[4] == ["SKU-4", "Notebook, A5", "3.2", "GBP", ""]


def test_missing_field_gives_empty_column():
    cfg = _cfg(fields=[*PRODUCT_FIELDS, "missing_col"], renames=PRODUCT_RENAMES)
    result = build_rows(_products(), cfg, set())
    assert result.header[-1] == "missing_col"
    assert all(row[-1] is None for row in result.rows)


def test_rename_collision_is_transform_error():
    cfg = _cfg(renames=[["sku", "title"]])
    with pytest.raises(TransformError, match="duplicate column name after rename: 'title'"):
        build_rows(_products(), cfg, set())


# AC-21: incremental filtering and key comparison
def test_incremental_v2_new_rows_match_fixture():
    cfg = _cfg(dedup_key="id", incremental=True)
    stored = {"1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008"}
    result = build_rows(ORDERS_V2, cfg, stored)
    assert _csv_view(result) == _fixture("orders_v2_new_rows.json")
    assert (
        len(ORDERS_V2),
        result.duplicates_removed,
        result.records_missing_key,
        result.already_seen_skipped,
        result.records_exported,
    ) == (14, 2, 1, 8, 3)
    assert result.exported_keys == ["1009", "1010", "1011"]
    _assert_invariant(result, len(ORDERS_V2))


def test_key_comparison_is_by_csv_text():
    cfg = _cfg(dedup_key="id")
    result = build_rows([{"id": 1}, {"id": "1"}], cfg, set())
    assert result.records_exported == 1
    assert result.duplicates_removed == 1
