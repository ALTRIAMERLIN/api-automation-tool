"""AC-08: the expected-output fixtures exist, parse, and have the right shape.

This module must not import anything from apitool. The fixtures are transcribed by hand.
"""

import json
from pathlib import Path

import pytest

EXPECTED_DIR = Path(__file__).parent / "fixtures" / "expected"

ROW_FILE_COUNTS = {
    "orders_dedup_rows.json": 9,
    "orders_nodedup_rows.json": 12,
    "orders_v2_new_rows.json": 4,
    "orders_v2_full_rows.json": 12,
    "events_rows.json": 6,
    "customers_xlsx.json": 7,
    "products_xlsx.json": 6,
}
ALL_FILES = [*ROW_FILE_COUNTS, "run_stats.json"]


def _load(name):
    return json.loads((EXPECTED_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ALL_FILES)
def test_fixture_exists_and_parses(name):
    assert (EXPECTED_DIR / name).is_file()
    _load(name)


@pytest.mark.parametrize(("name", "count"), ROW_FILE_COUNTS.items())
def test_row_count_includes_header(name, count):
    assert len(_load(name)) == count


@pytest.mark.parametrize("name", ROW_FILE_COUNTS)
def test_every_row_has_header_width(name):
    rows = _load(name)
    width = len(rows[0])
    assert all(len(row) == width for row in rows), name


def test_v2_full_is_v1_rows_then_padded_v2_new_rows():
    # SPEC/ACCEPTANCE 3.9: rows 1-8 of the v1 dedup file, then the v2 new rows padded to 12 cells.
    full = _load("orders_v2_full_rows.json")
    dedup = _load("orders_dedup_rows.json")
    new = _load("orders_v2_new_rows.json")
    assert full[0] == dedup[0]
    assert full[1:9] == dedup[1:9]
    assert full[9:] == [row + [""] * 3 for row in new[1:]]


def test_run_stats_has_five_demo_jobs_with_counters():
    stats = _load("run_stats.json")
    assert sorted(stats) == [
        "Demo Customers",
        "Demo Events",
        "Demo Flaky Orders",
        "Demo Orders",
        "Demo Products",
    ]
    for job in stats.values():
        assert set(job) == {
            "pages_fetched",
            "records_fetched",
            "retries",
            "duplicates_removed",
            "records_missing_key",
            "already_seen_skipped",
            "records_exported",
        }
