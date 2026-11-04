from apitool.transform import (
    clean_xlsx_text,
    csv_cell,
    flatten,
    render_csv,
    render_xlsx,
    sanitize_text,
    to_record,
)


# AC-16: flatten and render
def test_flatten_nested_dicts_and_keeps_lists():
    value = {"a": 1, "b": {"c": {"d": 2}, "e": {}}, "f": [1, {"g": 2}]}
    flat = flatten(value)
    assert flat == {"a": 1, "b.c.d": 2, "f": [1, {"g": 2}]}
    assert list(flat) == ["a", "b.c.d", "f"]


def test_to_record_wraps_non_dict_items():
    assert to_record("abc") == {"value": "abc"}
    assert to_record(7) == {"value": 7}
    assert to_record({"x": {"y": 1}}) == {"x.y": 1}


def test_render_csv_values():
    assert render_csv(None) == ""
    assert render_csv(True) == "true"
    assert render_csv(False) == "false"
    assert render_csv(0) == "0"
    assert render_csv(42.0) == "42.0"
    assert render_csv(-12.5) == "-12.5"
    assert render_csv("x") == "x"
    assert render_csv([]) == "[]"
    assert render_csv(["é", 1]) == '["é",1]'


def test_render_xlsx_values_and_types():
    assert render_xlsx(True) is True
    assert type(render_xlsx(True)) is bool
    assert render_xlsx(10**15 - 1) == 10**15 - 1
    assert type(render_xlsx(10**15 - 1)) is int
    assert render_xlsx(10**15) == "1000000000000000"
    assert render_xlsx(-(10**15)) == "-1000000000000000"
    assert render_xlsx(1.5) == 1.5
    assert render_xlsx(None) is None


# AC-17: sanitize_text
def test_sanitize_text_prefixes_formula_starts():
    assert sanitize_text("=1+1") == "'=1+1"
    assert sanitize_text("+x") == "'+x"
    assert sanitize_text("-x") == "'-x"
    assert sanitize_text("@x") == "'@x"
    assert sanitize_text("\tx") == "'\tx"
    assert sanitize_text("\rx") == "'\rx"


def test_sanitize_text_leaves_other_text_alone():
    assert sanitize_text("a=b") == "a=b"
    assert sanitize_text("") == ""
    assert sanitize_text("[1]") == "[1]"


def test_csv_cell_sanitizes_only_strings():
    # A float -12.5 is not a string, so it is never prefixed. A string "-5" is.
    assert csv_cell(-12.5) == "-12.5"
    assert csv_cell("-5") == "'-5"


def test_clean_xlsx_text_removes_control_characters():
    assert clean_xlsx_text("a\x01b", sanitize=False) == ("ab", False)


def test_clean_xlsx_text_truncates_long_text():
    text, truncated = clean_xlsx_text("y" * 40000, sanitize=False)
    assert len(text) == 32767
    assert truncated is True
