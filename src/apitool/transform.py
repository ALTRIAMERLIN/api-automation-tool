"""Flattening and value rendering for CSV and XLSX (SPEC 9.1, 9.3, 9.4, 9.5)."""

import json
import re
from typing import Any

XLSX_MAX_TEXT = 32767
_XLSX_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_XLSX_MAX_INT = 10**15
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def flatten(obj: dict, prefix: str = "") -> dict:
    """Flatten nested dicts into dotted keys. Lists are kept as values. Empty dicts add nothing."""
    out: dict = {}
    for key, value in obj.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten(value, full_key))
        else:
            out[full_key] = value
    return out


def to_record(item: Any) -> dict:
    """Turn one raw item from the records list into a flat dict. Non-dicts become {"value": x}."""
    if not isinstance(item, dict):
        item = {"value": item}
    return flatten(item)


def _list_json(value: list) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_csv(value: Any) -> str:
    """Text for one CSV cell (SPEC 9.3)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return value
    return _list_json(value)


def render_xlsx(value: Any) -> Any:
    """Value to store in an XLSX cell (SPEC 9.3)."""
    if value is None or isinstance(value, bool | float | str):
        return value
    if isinstance(value, int):
        return value if abs(value) < _XLSX_MAX_INT else str(value)
    return _list_json(value)


def sanitize_text(text: str) -> str:
    """Prefix a quote when text would start a spreadsheet formula (SPEC 9.4)."""
    if text and text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def csv_cell(value: Any) -> str:
    """CSV text for a cell. Only values that were originally strings are sanitized."""
    if isinstance(value, str):
        return sanitize_text(value)
    return render_csv(value)


def clean_xlsx_text(text: str, sanitize: bool) -> tuple[str, bool]:
    """Remove control characters, optionally sanitize, then cut to the Excel limit (SPEC 9.5).

    Returns the cleaned text and whether it was truncated.
    """
    cleaned = _XLSX_CONTROL_RE.sub("", text)
    if sanitize:
        cleaned = sanitize_text(cleaned)
    if len(cleaned) > XLSX_MAX_TEXT:
        return cleaned[:XLSX_MAX_TEXT], True
    return cleaned, False
