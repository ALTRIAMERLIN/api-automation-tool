from apitool.jsonpath import MISSING, get_path

# AC-05
OBJ = {"a": {"b": [{"c": 1}], "n": None}}


def test_empty_path_returns_object_itself():
    assert get_path(OBJ, "") is OBJ


def test_nested_dict_and_list_index():
    assert get_path(OBJ, "a.b.0.c") == 1


def test_present_null_is_none_not_missing():
    assert get_path(OBJ, "a.n") is None


def test_missing_key_is_missing():
    assert get_path(OBJ, "a.x") is MISSING


def test_index_out_of_range_is_missing():
    assert get_path(OBJ, "a.b.5") is MISSING


def test_non_digit_segment_on_list_is_missing():
    assert get_path(OBJ, "a.b.c") is MISSING


def test_descending_past_scalar_is_missing():
    assert get_path(OBJ, "a.b.0.c.d") is MISSING


def test_list_root_with_index():
    assert get_path([10, 20], "1") == 20


def test_non_ascii_digit_segment_is_missing_not_a_crash():
    # "²" is a Unicode digit: str.isdigit() accepts it, but int() rejects it.
    assert get_path([10, 20], "²") is MISSING


def test_missing_sentinel_is_unique_and_not_none():
    assert MISSING is not None
    assert MISSING is get_path({}, "x")
