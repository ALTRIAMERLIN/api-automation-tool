"""Export files: CSV and XLSX writers, file names and safe paths (SPEC 11)."""

import csv
import os
from pathlib import Path
from typing import Any

from apitool.errors import ExportError
from apitool.transform import csv_cell, sanitize_text


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> list[str]:
    """Write a UTF-8 (with BOM) CSV atomically: temp file first, then rename (SPEC 11.2, 11.3).

    Returns the warnings list, which is always empty for CSV.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([sanitize_text(name) for name in header])
            for row in rows:
                writer.writerow([csv_cell(value) for value in row])
        os.replace(tmp, path)
    except Exception as exc:
        _remove_quietly(tmp)
        raise ExportError(f"could not write export: {type(exc).__name__}") from None
    return []
