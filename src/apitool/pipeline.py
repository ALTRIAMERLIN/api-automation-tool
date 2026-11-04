"""Raw records to filtered rows: flatten, dedup, incremental filter, columns, rename (SPEC 9.2)."""

from dataclasses import dataclass, field
from typing import Any

from apitool.config import JobConfig
from apitool.errors import TransformError
from apitool.jsonpath import MISSING
from apitool.transform import render_csv, to_record


@dataclass
class PipelineResult:
    header: list[str]
    rows: list[list[Any]]
    exported_keys: list[str] = field(default_factory=list)
    duplicates_removed: int = 0
    records_missing_key: int = 0
    already_seen_skipped: int = 0
    records_exported: int = 0
    warnings: list[str] = field(default_factory=list)


def _columns(kept: list[dict], fields: list[str]) -> list[str]:
    if fields:
        return list(fields)
    columns: list[str] = []
    seen: set[str] = set()
    for record in kept:
        for key in record:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def build_rows(raw_records: list[Any], cfg: JobConfig, stored_keys: set[str]) -> PipelineResult:
    """Run the SPEC 9.2 pipeline in its exact order. Pure: no storage, no environment."""
    flat = [to_record(item) for item in raw_records]

    missing = 0
    duplicates = 0
    already_seen = 0
    kept: list[dict] = []
    exported_keys: list[str] = []

    if cfg.dedup_key:
        seen_in_run: set[str] = set()
        for record in flat:
            value = record.get(cfg.dedup_key, MISSING)
            if value is MISSING or value is None or render_csv(value) == "":
                missing += 1
                continue
            key = render_csv(value)
            if key in seen_in_run:
                duplicates += 1
                continue
            seen_in_run.add(key)
            if cfg.incremental and key in stored_keys:
                already_seen += 1
                continue
            kept.append(record)
            exported_keys.append(key)
    else:
        kept = flat

    warnings: list[str] = []
    if missing > 0:
        warnings.append(
            f"missing_key: {missing} records skipped because key field "
            f"'{cfg.dedup_key}' was missing or empty"
        )

    columns = _columns(kept, cfg.fields)
    renames = dict(cfg.renames)
    header = [renames.get(column, column) for column in columns]

    seen_names: set[str] = set()
    for name in header:
        if name in seen_names:
            raise TransformError(f"duplicate column name after rename: '{name}'")
        seen_names.add(name)

    rows = [[record.get(column, None) for column in columns] for record in kept]

    return PipelineResult(
        header=header,
        rows=rows,
        exported_keys=exported_keys,
        duplicates_removed=duplicates,
        records_missing_key=missing,
        already_seen_skipped=already_seen,
        records_exported=len(rows),
        warnings=warnings,
    )
