import csv
import json
from pathlib import Path

import pytest

from apitool import export
from apitool.config import build_job_config
from apitool.demo.data import EVENTS_PAGES, ORDERS_V1
from apitool.errors import ExportError
from apitool.export import write_csv
from apitool.pipeline import build_rows

EXPECTED = Path(__file__).parent / "fixtures" / "expected"


def _cfg(**overrides):
    base = {"name": "Csv", "url": "https://api.example.com/v1/x", "pagination_type": "none"}
    return build_job_config({**base, **overrides})


def _read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


# AC-22: exact bytes for the events export (SPEC 11.3, ACCEPTANCE 3.5)
def test_events_csv_bytes_are_exact(tmp_path):
    raw = [record for page in EVENTS_PAGES for record in page["results"]]
    result = build_rows(raw, _cfg(dedup_key="event_id"), set())
    target = tmp_path / "events.csv"
    write_csv(target, result.header, result.rows)

    lines = [
        b"event_id,type,ts,payload.plan,payload.seats,payload.reason",
        b"evt_001,signup,2026-10-01T09:00:00Z,pro,5,",
        b"evt_002,upgrade,2026-10-02T12:30:00Z,team,12,",
        b"evt_003,login,2026-10-03T08:15:00Z,,,",
        b'evt_004,cancel,2026-10-04T17:45:00Z,pro,,"too expensive, for now"',
        b"evt_005,signup,2026-10-05T10:00:00Z,free,1,",
    ]
    expected = b"\xef\xbb\xbf" + b"\r\n".join(lines) + b"\r\n"
    assert target.read_bytes() == expected


def test_orders_csv_reads_back_and_has_raw_lines(tmp_path):
    result = build_rows(ORDERS_V1, _cfg(dedup_key="id"), set())
    target = tmp_path / "orders.csv"
    write_csv(target, result.header, result.rows)

    expected_rows = json.loads((EXPECTED / "orders_dedup_rows.json").read_text("utf-8"))
    assert _read_rows(target) == expected_rows

    text = target.read_bytes().decode("utf-8-sig")
    raw_lines = [
        '1003,paid,120.5,EUR,Zoë Müller,zoe@example.de,"[""intl""]",true,'
        '"Line one\nLine two",,,\r\n',
        '1004,refunded,0,USD,"\'=HYPERLINK(""http://evil.example"")",mallory@example.com,'
        '"[""flagged""]",false,\'-discount applied,,,\r\n',
        '1002,pending,5,USD,"Bob, Jr.",bob@example.com,[],false,"Leave at ""back"" door",,,\r\n',
    ]
    for line in raw_lines:
        assert line in text


# AC-23: atomic write
def test_failed_write_leaves_no_file_and_raises_export_error(tmp_path, monkeypatch):
    real_writer = export.csv.writer
    calls = {"n": 0}

    class FailingWriter:
        def __init__(self, handle):
            self._inner = real_writer(handle)

        def writerow(self, row):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("disk full")
            return self._inner.writerow(row)

    monkeypatch.setattr(export.csv, "writer", FailingWriter)
    target = tmp_path / "out.csv"
    with pytest.raises(ExportError, match="could not write export: OSError"):
        write_csv(target, ["a", "b"], [[1, 2], [3, 4], [5, 6]])
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
