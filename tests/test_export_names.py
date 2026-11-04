from datetime import UTC, datetime, timedelta, timezone

from apitool.export import export_filename, safe_export_path, slugify


# AC-26: slugs
def test_slugify_plain_name():
    assert slugify("Demo Orders") == "demo-orders"


def test_slugify_accents_and_punctuation():
    # Lowercasing keeps the accents, so ü and ï are non [a-z0-9] characters.
    # Runs: "  --ü", "ï", "!! ", "__ " -> leaves "n", "code", "job" -> "n-code-job".
    assert slugify("  --Ünïcode!! Job__ ") == "n-code-job"


def test_slugify_empty_result_is_job():
    assert slugify("!!!") == "job"


# AC-26: file names
def test_export_filename_uses_utc_stamp_and_run_id():
    started = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)
    assert export_filename("Demo Orders", started, 7, "csv") == (
        "demo-orders_20261104-100000_run7.csv"
    )


def test_export_filename_converts_to_utc():
    # 18:00 at UTC+8 is 10:00 UTC.
    plus8 = timezone(timedelta(hours=8))
    started = datetime(2026, 11, 4, 18, 0, 0, tzinfo=plus8)
    assert export_filename("Demo Orders", started, 7, "csv") == (
        "demo-orders_20261104-100000_run7.csv"
    )


# AC-26: safe paths
def test_unsafe_names_are_rejected(tmp_path):
    exports = tmp_path / "exports"
    exports.mkdir()
    assert safe_export_path(exports, "../x.csv") is None
    assert safe_export_path(exports, "C:\\x.csv") is None
    assert safe_export_path(exports, "") is None
    assert safe_export_path(exports, "sub/x.csv") is None
    assert safe_export_path(exports, "..") is None


def test_plain_name_is_inside_resolved_exports_dir(tmp_path):
    exports = tmp_path / "exports"
    exports.mkdir()
    assert safe_export_path(exports, "a.csv") == exports.resolve() / "a.csv"
