"""Export files: CSV and XLSX writers, file names and safe paths (SPEC 11)."""

import csv
import os
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from apitool.errors import ExportError
from apitool.transform import clean_xlsx_text, csv_cell, render_xlsx, sanitize_text

XLSX_MAX_ROWS = 1_048_576


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


def write_xlsx(path: Path, header: list[str], rows: list[list[Any]]) -> list[str]:
    """Write an .xlsx file atomically (SPEC 11.4). Returns warnings such as excel_truncated."""
    if len(rows) + 1 > XLSX_MAX_ROWS:
        raise ExportError("too many rows for Excel")

    truncated = 0
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "data"

    for column, name in enumerate(header, start=1):
        text, cut = clean_xlsx_text(name, sanitize=True)
        truncated += int(cut)
        cell = sheet.cell(row=1, column=column, value=text)
        cell.font = Font(bold=True)
        letter = get_column_letter(column)
        sheet.column_dimensions[letter].width = min(50, max(10, len(name) + 2))

    for row_number, row in enumerate(rows, start=2):
        for column, value in enumerate(row, start=1):
            stored = render_xlsx(value)
            if isinstance(stored, str):
                # Formula sanitizing applies only when the original value was a string.
                stored, cut = clean_xlsx_text(stored, sanitize=isinstance(value, str))
                truncated += int(cut)
            sheet.cell(row=row_number, column=column, value=stored)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(header))}{len(rows) + 1}"

    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as handle:
            workbook.save(handle)
        os.replace(tmp, path)
    except Exception as exc:
        _remove_quietly(tmp)
        raise ExportError(f"could not write export: {type(exc).__name__}") from None

    warnings: list[str] = []
    if truncated:
        warnings.append(
            f"excel_truncated: {truncated} cell values longer than 32767 characters were truncated"
        )
    return warnings
