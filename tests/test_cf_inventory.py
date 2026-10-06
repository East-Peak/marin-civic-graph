"""The effective inventory of landed NetFile exports: what data/raw offers, per source and year.

Every file here is synthetic (tests/netfile_workbooks.py) and lives in tmp_path; nothing reads the real data/.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cf_inventory as inv  # noqa: E402
from tests.netfile_workbooks import filing, summary, write_export  # noqa: E402

HTML_PAGE = b"\r\n<!DOCTYPE html>\n<html><body>Sign in</body></html>\n"
TODAY = date(2026, 10, 12)
SOURCE = {"id": "example-cf", "name": "Example County", "agency_code": "EXC",
          "portal_url": "https://netfile.example/public/EXC/campaign", "backfill_from": "2024-01-01"}


def _export(path: Path, rpt: str = "2025-01-31") -> Path:
    f = filing(rpt=rpt)
    return write_export(path, {"Summary": [summary(f, "A", "1", 0)]})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(raw: Path, source: dict = SOURCE, cache: dict | None = None, today: date = TODAY):
    return inv.inventory(raw, [source], today, {} if cache is None else cache)[source["id"]]


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


def test_each_year_selects_the_newest_capture_and_records_its_latest_report_date(raw):
    _export(raw / "example-cf/2026-04-14/2024.zip", rpt="2025-01-20")
    _export(raw / "example-cf/2026-04-14/2025.zip", rpt="2026-01-31")
    newer = _export(raw / "example-cf/2026-10-01/2025.zip", rpt="2026-06-11")

    years = _inventory(raw).years

    assert years["2024"].status == "selected" and years["2024"].selected.capture == "2026-04-14"
    assert years["2025"].selected.capture == "2026-10-01"  # a newer capture may hold only some years
    assert years["2025"].selected.path == "example-cf/2026-10-01/2025.zip"
    assert years["2025"].selected.sha256 == _sha(newer)
    assert years["2025"].selected.latest_report_date == "2026-06-11"
    assert years["2026"].status == "missing" and years["2026"].selected is None


def test_an_invalid_newest_file_holds_the_year_and_never_falls_back_to_an_older_one(raw):
    _export(raw / "example-cf/2026-04-14/2025.zip")
    (raw / "example-cf/2026-10-01").mkdir(parents=True)
    (raw / "example-cf/2026-10-01/2025.zip").write_bytes(HTML_PAGE)

    entry = _inventory(raw).years["2025"]

    assert entry.status == "held" and entry.selected is None
    assert entry.held.path == "example-cf/2026-10-01/2025.zip"
    assert "HTML page" in entry.held.reason


def test_a_corrupt_or_wrong_workbook_is_held_with_the_validators_reason(raw):
    (raw / "example-cf/2026-10-01").mkdir(parents=True)
    (raw / "example-cf/2026-10-01/2025.zip").write_bytes(b"PK\x03\x04 truncated")
    write_export(raw / "example-cf/2026-10-01/2026.zip", {}, sheets=["Summary"])

    years = _inventory(raw).years

    assert years["2025"].status == "held" and "not a readable workbook" in years["2025"].held.reason
    assert years["2026"].status == "held" and "missing sheet" in years["2026"].held.reason


def test_a_pinned_page_is_unavailable_coverage_only_for_that_exact_file(raw):
    (raw / "example-cf/2026-04-14").mkdir(parents=True)
    (raw / "example-cf/2026-04-14/2024.zip").write_bytes(HTML_PAGE)
    (raw / "example-cf/2026-10-01").mkdir(parents=True)
    (raw / "example-cf/2026-10-01/2025.zip").write_bytes(HTML_PAGE)  # same bytes, not pinned here
    pin = {"capture": "2026-04-14", "file": "2024.zip", "sha256": hashlib.sha256(HTML_PAGE).hexdigest()}

    years = _inventory(raw, {**SOURCE, "unavailable_inputs": [pin]}).years

    assert years["2024"].status == "pinned" and years["2024"].pinned.path == "example-cf/2026-04-14/2024.zip"
    assert years["2025"].status == "held"


def test_confirmed_unavailable_marks_missing_coverage_but_never_excuses_a_bad_submission(raw):
    (raw / "example-cf/2026-10-01").mkdir(parents=True)
    (raw / "example-cf/2026-10-01/2025.zip").write_bytes(HTML_PAGE)
    confirmed = [{"year": "2024", "confirmed": "2026-10-01", "reason": "the portal lists no export"},
                 {"year": "2025", "confirmed": "2026-10-01", "reason": "the portal lists no export"}]

    years = _inventory(raw, {**SOURCE, "confirmed_unavailable": confirmed}).years

    assert years["2024"].status == "missing" and years["2024"].confirmed["confirmed"] == "2026-10-01"
    assert years["2025"].status == "held"  # a landed file is judged on its own


@pytest.mark.parametrize("entry,says", [
    ({"year": "2024"}, "confirmed"),
    ({"year": "2024", "confirmed": "2026-13-01", "reason": "x"}, "confirmed"),
    ({"year": "2024", "confirmed": "2026-10-01", "reason": " "}, "reason"),
    ({"year": "1999", "confirmed": "2026-10-01", "reason": "x"}, "1999"),
])
def test_a_malformed_confirmation_is_a_config_error(raw, entry, says):
    with pytest.raises(inv.ConfigError, match=says):
        _inventory(raw, {**SOURCE, "confirmed_unavailable": [entry]})


def test_misnamed_files_and_dirs_are_landed_but_not_ready_with_the_fix(raw):
    _export(raw / "example-cf/2026-10-01/EXC_2026_Amended_Transactions.zip")
    _export(raw / "example-cf/2026-10-1/2026.zip")
    _export(raw / "example-cf/2026-11-30/2026.zip")  # a capture dated after today
    _export(raw / "example-cf/2026-10-01/2031.zip")
    (raw / "example-cf/notes.txt").write_text("x")

    problems = {p.path: p.reason for p in _inventory(raw).landed_problems}

    assert "2026.zip" in problems["example-cf/2026-10-01/EXC_2026_Amended_Transactions.zip"]
    assert "YYYY-MM-DD" in problems["example-cf/2026-10-1"]
    assert "after today" in problems["example-cf/2026-11-30"]
    assert "2031" in problems["example-cf/2026-10-01/2031.zip"]
    assert "example-cf/notes.txt" in problems
    assert _inventory(raw).years["2026"].status == "missing"


def test_validation_is_cached_by_content_hash(raw, monkeypatch):
    path = _export(raw / "example-cf/2026-10-01/2025.zip", rpt="2026-02-01")
    cache: dict = {}
    first = _inventory(raw, cache=cache)
    calls = []
    monkeypatch.setattr(inv, "validate_export", lambda p: calls.append(p))

    second = _inventory(raw, cache=cache)

    assert calls == [] and cache[_sha(path)] == {"ok": True, "reason": None, "latest_report_date": "2026-02-01"}
    assert first.years["2025"].selected == second.years["2025"].selected


def test_the_selection_id_changes_with_bytes_status_or_capture_date(raw):
    _export(raw / "example-cf/2026-04-14/2025.zip")
    base = inv.inventory(raw, [SOURCE], TODAY, {})
    again = inv.inventory(raw, [SOURCE], TODAY, {})
    _export(raw / "example-cf/2026-10-01/2025.zip")  # identical bytes, later download
    later = inv.inventory(raw, [SOURCE], TODAY, {})

    assert inv.selection_id(base) == inv.selection_id(again)
    assert inv.selection_id(later) != inv.selection_id(base)


def test_a_source_with_no_captures_has_every_year_missing(raw):
    years = _inventory(raw).years
    assert sorted(years) == ["2024", "2025", "2026"] and {y.status for y in years.values()} == {"missing"}
