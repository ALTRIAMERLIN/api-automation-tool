import json
from pathlib import Path

import openpyxl
import pytest

from apitool import export
from apitool.config import build_job_config
from apitool.demo.data import CUSTOMERS, PRODUCTS_PAGES
from apitool.errors import ExportError
from apitool.export import write_xlsx
from apitool.pipeline import build_rows

EXPECTED = Path(__file__).parent / "fixtures" / "expected"


def _cfg(**overrides):
    base = {"name": "Xlsx", "url": "https://api.example.com/v1/x", "pagination_type": "none"}
    return build_job_config({**base, **overrides})


def _fixture(name):
    return json.loads((EXPECTED / name).read_text(encoding="utf-8"))


def _sheet(path):
    return openpyxl.load_workbook(path)["data"]


def _values(path):
    return [list(row) for row in _sheet(path).iter_rows(values_only=True)]


def _column_widths(sheet):
    # openpyxl may merge equal-width neighbours into one entry (ACCEPTANCE 3.6).
    widths = {}
    for dim in sheet.column_dimensions.values():
        for index in range(dim.min, dim.max + 1):
            widths[index] = dim.width
    return widths


def _assert_same_values_and_types(actual_rows, expected_rows):
    assert len(actual_rows) == len(expected_rows)
    for actual, expected in zip(actual_rows, expected_rows, strict=True):
        assert [type(v) for v in actual] == [type(v) for v in expected], (actual, expected)
        assert actual == expected


# AC-24: customers and products read back
def test_customers_xlsx_values_types_and_formatting(tmp_path):
    result = build_rows(CUSTOMERS, _cfg(), set())
    target = tmp_path / "customers.xlsx"
    warnings = write_xlsx(target, result.header, result.rows)
    assert warnings == []

    expected = _fixture("customers_xlsx.json")
    _assert_same_values_and_types(_values(target), expected)

    sheet = _sheet(target)
    assert sheet.title == "data"
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:G7"
    for column in "ABCDEFG":
        assert sheet[f"{column}1"].font.bold is True
    widths = _column_widths(sheet)
    assert [widths[i] for i in range(1, 8)] == [10, 10, 10, 10, 14, 15, 10]


def test_products_xlsx_values_and_filter(tmp_path):
    raw = [item for page in PRODUCTS_PAGES for item in page["items"]]
    cfg = _cfg(
        fields=["sku", "title", "price.amount", "price.currency", "stock"],
        renames=[["price.amount", "price"], ["price.currency", "currency"]],
    )
    result = build_rows(raw, cfg, set())
    target = tmp_path / "products.xlsx"
    write_xlsx(target, result.header, result.rows)

    _assert_same_values_and_types(_values(target), _fixture("products_xlsx.json"))
    assert _sheet(target).auto_filter.ref == "A1:E6"


# AC-25: edge cases
def test_excel_edge_cases(tmp_path):
    target = tmp_path / "edge.xlsx"
    header = ["=bad", "x"]
    rows = [["a\x01b", "y" * 40000], [10**15, -(10**15) + 1]]
    warnings = write_xlsx(target, header, rows)

    sheet = _sheet(target)
    assert sheet["A1"].value == "'=bad"
    assert sheet["A2"].value == "ab"
    assert len(sheet["B2"].value) == 32767
    assert sheet["A3"].value == "1000000000000000"
    assert isinstance(sheet["A3"].value, str)
    assert sheet["B3"].value == -999999999999999
    assert type(sheet["B3"].value) is int
    assert warnings == [
        "excel_truncated: 1 cell values longer than 32767 characters were truncated"
    ]


def test_xlsx_atomic_failure_leaves_no_file(tmp_path, monkeypatch):
    def boom(self, handle):
        raise OSError("disk full")

    monkeypatch.setattr(export.Workbook, "save", boom)
    with pytest.raises(ExportError, match="could not write export: OSError"):
        write_xlsx(tmp_path / "x.xlsx", ["a"], [[1]])
    assert list(tmp_path.iterdir()) == []


def test_too_many_rows_is_checked_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "XLSX_MAX_ROWS", 2)
    with pytest.raises(ExportError, match="too many rows for Excel"):
        write_xlsx(tmp_path / "x.xlsx", ["a"], [[1], [2]])
    assert list(tmp_path.iterdir()) == []
