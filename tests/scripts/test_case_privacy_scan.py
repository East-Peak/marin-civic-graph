"""Tests for scripts/case_privacy_scan.py. Only fictional sentinel names appear here."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import case_privacy_scan as ps  # noqa: E402

XML = """<?xml version="1.0"?>
<Return xmlns="http://www.irs.gov/efile"><ReturnData><IRS990>
  <Officers><PersonNm>Quillon Testperson</PersonNm><BusinessName><BusinessNameLine1Txt>Example Fund</BusinessNameLine1Txt></BusinessName></Officers>
  <PreparerPersonNm>Marlowe Samplesmith</PreparerPersonNm>
  <OtherPersonNm>Q Initial Fakeman</OtherPersonNm>
</IRS990></ReturnData></Return>
"""


def _ledger(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _ind(first: str, last: str, cd: str = "IND") -> dict:
    return {"entity_cd": cd, "name": {"first": first, "last": last, "title": None, "suffix": None}}


class TestSources:
    def test_990_person_names(self, tmp_path):
        xml = tmp_path / "r.xml"
        xml.write_text(XML)
        names = {n for n, _ in ps.forbidden_from_990([xml])}
        assert {"Quillon Testperson", "Marlowe Samplesmith", "Q Initial Fakeman"} <= names
        assert "Example Fund" not in names
        assert {c for _, c in ps.forbidden_from_990([xml])} == {"990_person"}

    def test_ledger_ind_rows_both_orders(self, tmp_path):
        led = _ledger(tmp_path / "l.jsonl", [_ind("Ardith", "Mockwell"), _ind("Org", "Committee", cd="COM")])
        entries = ps.forbidden_from_ledger([led])
        assert set(entries) == {("Ardith Mockwell", "individual_contributor"),
                                ("Mockwell, Ardith", "individual_contributor")}

    def test_extra_list_skips_blanks_and_comments(self, tmp_path):
        f = tmp_path / "extra.txt"
        f.write_text("# header\n\nBrennick Notreal\n")
        assert ps.forbidden_from_file(f) == [("Brennick Notreal", "operator_list")]


class TestBuild:
    def test_single_token_and_short_token_names_are_skipped_and_counted(self):
        names, skipped = ps.build_forbidden([("Madeupname", "operator_list"), ("A Person", "operator_list"),
                                             ("Valid Person", "operator_list")], allow=[])
        assert list(names.values()) == ["operator_list"] and skipped == 2

    def test_middle_initial_names_keep_the_initial_free_variant(self):
        names, skipped = ps.build_forbidden([("Jorvan Q Fictional", "990_person")], allow=[])
        assert "jorvan fictional" in names and skipped == 0

    def test_allowlist_removes_case_insensitively_in_both_orders(self):
        entries = [("Quillon Testperson", "990_person"), ("Testperson, Quillon", "990_person"),
                   ("Marlowe Samplesmith", "990_person")]
        names, _ = ps.build_forbidden(entries, allow=["QUILLON testperson"])
        assert list(names) == ["marlowe samplesmith"]

    def test_first_category_wins(self):
        names, _ = ps.build_forbidden([("Same Name", "990_person"), ("same  name", "operator_list")], allow=[])
        assert names == {"same name": "990_person"}


class TestScan:
    def forbidden(self):
        return ps.build_forbidden([("Quillon Testperson", "990_person"), ("Testperson, Quillon", "990_person"),
                                   ("Ardith Mockwell", "individual_contributor")], allow=[])[0]

    def test_whole_word_case_insensitive_whitespace_normalized(self, tmp_path):
        f = tmp_path / "out.md"
        f.write_text("fine\nsigned by QUILLON   TESTPERSON today\nQuillon\nTestperson wrote\n"
                     "Quillon Testpersonality is not a hit\nTestperson, Quillon again; Ardith Mockwell too\n")
        hits = ps.scan([f], self.forbidden())
        assert hits == [{"file": str(f), "line": 2, "category": "990_person"},
                        {"file": str(f), "line": 3, "category": "990_person"},
                        {"file": str(f), "line": 6, "category": "990_person"},
                        {"file": str(f), "line": 6, "category": "individual_contributor"}]

    def test_output_never_contains_the_value(self, tmp_path):
        f = tmp_path / "out.md"
        f.write_text("Quillon Testperson\n")
        hits = ps.scan([f], self.forbidden())
        assert "quillon" not in json.dumps(hits).lower() and "testperson" not in json.dumps(hits).lower()

    def test_clean_file_no_hits(self, tmp_path):
        f = tmp_path / "out.md"
        f.write_text("Example Fund granted money.\n")
        assert ps.scan([f], self.forbidden()) == []

    def test_missing_file_error_does_not_leak(self, tmp_path):
        with pytest.raises(OSError) as err:
            ps.scan([tmp_path / "gone.md"], self.forbidden())
        assert "testperson" not in str(err.value).lower()


class TestCli:
    def test_hit_exits_one_and_prints_no_value(self, tmp_path, capsys):
        xml = tmp_path / "r.xml"
        xml.write_text(XML)
        led = _ledger(tmp_path / "l.jsonl", [_ind("Ardith", "Mockwell")])
        out = tmp_path / "CASE.md"
        out.write_text("ok\nQuillon Testperson was named.\n")
        code = ps.main(["--scan", str(out), "--xml", str(xml), "--ledger", str(led)])
        text = capsys.readouterr().out
        assert code == 1 and f"{out}:2:990_person" in text and "Testperson" not in text and "Mockwell" not in text

    def test_allowlist_and_clean_run_exit_zero(self, tmp_path, capsys):
        xml = tmp_path / "r.xml"
        xml.write_text(XML)
        allow = tmp_path / "allow.txt"
        allow.write_text("Quillon Testperson\nMarlowe Samplesmith\nQ Initial Fakeman\n")
        out = tmp_path / "CASE.md"
        out.write_text("Quillon Testperson signed in an official capacity.\n")
        assert ps.main(["--scan", str(out), "--xml", str(xml), "--allow", str(allow)]) == 0
        assert "0 hits" in capsys.readouterr().out

    def test_extra_list_and_skipped_count_reported(self, tmp_path, capsys):
        extra = tmp_path / "extra.txt"
        extra.write_text("Brennick Notreal\nSingle\n")
        out = tmp_path / "x.md"
        out.write_text("Brennick Notreal\n")
        assert ps.main(["--scan", str(out), "--extra", str(extra)]) == 1
        text = capsys.readouterr().out
        assert "operator_list" in text and "skipped 1" in text
