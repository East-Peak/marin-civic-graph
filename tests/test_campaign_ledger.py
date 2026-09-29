"""The campaign-finance ledger: every physical row, filings, and Schedule A/E reconciliation."""
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from campaign_ledger import LedgerError, build_ledger
from tests.netfile_workbooks import contribution, expenditure, filing, other, summary, write_export

F1 = filing()


def _ledger(tmp_path, sheets_by_year: dict, **kwargs):
    workbooks = [(f"src/2026-04-14/{year}.zip", write_export(tmp_path / f"{year}.zip", sheets))
                 for year, sheets in sorted(sheets_by_year.items())]
    return build_ledger("src", workbooks, **kwargs)


def _status(ledger, f: dict, schedule: str) -> dict:
    fid = ledger.filing_id_for(source_id="src", **f)
    return next(r for r in ledger.reconciliation if r["filing_id"] == fid and r["schedule"] == schedule)


def _a_e_rows(ledger):
    return [r for r in ledger.rows if r["schedule"] in ("A", "E")]


class TestReconciliation:
    def test_signed_decimal_cents_match_the_summary_oracle(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 100.10), contribution(F1, "a2", 200.20),
                                contribution(F1, "a3", -50.05, Tran_Type="R")],
            "Summary": [summary(F1, "A", "1", 250.25)],
        }})
        status = _status(ledger, F1, "A")
        assert status["status"] == "matched"
        assert status["itemized"] == "250.25" and status["oracle"] == "250.25"
        assert not ledger.errors

    def test_f460_line_1_is_not_the_oracle(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 100)],
            "Summary": [summary(F1, "F460", "1", 100)],
        }})
        assert _status(ledger, F1, "A")["status"] == "missing_oracle"

    def test_an_unexplained_mismatch_is_an_error(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 100)],
            "Summary": [summary(F1, "A", "1", 150)],
        }})
        assert _status(ledger, F1, "A")["status"] == "mismatched"
        assert any("mismatched" in e for e in ledger.errors)

    def test_an_exception_needs_a_locator_and_independent_evidence(self, tmp_path):
        sheets = {"2024": {"A-Contributions": [contribution(F1, "a1", 100)],
                           "Summary": [summary(F1, "A", "1", 150)]}}
        fid = build_ledger("src", []).filing_id_for(source_id="src", **F1)
        with pytest.raises(LedgerError, match="evidence"):
            _ledger(tmp_path, sheets, exceptions=[{"filing_id": fid, "schedule": "A", "locator": "x"}])
        ledger = _ledger(tmp_path, sheets, exceptions=[{
            "filing_id": fid, "schedule": "A", "locator": "src/2026-04-14/2024.zip!Summary!2",
            "evidence": "filer's F460 cover shows the $50 as a late itemization carried to the next period"}])
        assert _status(ledger, F1, "A")["status"] == "excepted"
        assert not ledger.errors

    def test_missing_oracle_stays_unreconciled_and_unvalidated(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 100), contribution(F1, "a2", -100, Tran_Type="R")],
            "E-Expenditure": [expenditure(F1, "e1", 40)],
            "Summary": [summary(F1, "E", "1", 40)],
        }})
        assert _status(ledger, F1, "A")["status"] == "missing_oracle"
        assert _status(ledger, F1, "A")["validated"] is False
        assert _status(ledger, F1, "E")["validated"] is True

    def test_summary_only_filings_are_enumerated(self, tmp_path):
        quiet = filing(filer_id="1400002", name="Quiet Committee")
        ledger = _ledger(tmp_path, {"2024": {"Summary": [summary(quiet, "A", "1", 0), summary(quiet, "F460", "1", 0)]}})
        assert ledger.filing_id_for(source_id="src", **quiet) in ledger.filings
        assert _status(ledger, quiet, "A")["status"] == "matched"
        assert _status(ledger, quiet, "A")["rows"] == 0

    def test_an_oracle_without_rows_must_be_zero(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {"Summary": [summary(F1, "A", "1", 75)]}})
        assert _status(ledger, F1, "A")["status"] == "mismatched"

    def test_notice_only_filings_without_a_period_are_enumerated(self, tmp_path):
        notice = filing(start=None, thru=None, rpt="2024-10-30")
        ledger = _ledger(tmp_path, {"2024": {"497": [{**notice, "Rec_Type": "RCPT", "Form_Type": "F497P1",
                                                       "Tran_ID": "n1", "Amount": 5000}]}})
        fid = ledger.filing_id_for(source_id="src", **notice)
        assert ledger.filings[fid]["from_date"] is None
        assert not [r for r in ledger.reconciliation if r["filing_id"] == fid]

    def test_counts_are_reported_per_schedule_and_status(self, tmp_path):
        other_filing = filing(rpt="2024-03-01", start="2024-01-21", thru="2024-02-20")
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10), contribution(other_filing, "a2", 5)],
            "Summary": [summary(F1, "A", "1", 10), summary(other_filing, "E", "1", 0)],
        }})
        counts = ledger.counts()
        assert counts["A"]["with_rows"] == {"matched": 1, "missing_oracle": 1}
        assert counts["E"]["summary_only"] == {"matched": 1}


class TestFilingKeys:
    def test_same_key_in_two_files_is_ambiguous_and_never_merged(self, tmp_path):
        ledger = _ledger(tmp_path, {
            "2023": {"A-Contributions": [contribution(F1, "a1", 10)], "Summary": [summary(F1, "A", "1", 10)]},
            "2024": {"A-Contributions": [contribution(F1, "a2", 10)], "Summary": [summary(F1, "A", "1", 10)]},
        })
        status = _status(ledger, F1, "A")
        assert status["status"] == "ambiguous" and status["validated"] is False
        assert "multiple_files" in ledger.filings[status["filing_id"]]["ambiguous"]

    def test_two_oracle_lines_are_ambiguous(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10)],
            "Summary": [summary(F1, "A", "1", 10), summary(F1, "A", "1", 10)],
        }})
        assert _status(ledger, F1, "A")["status"] == "ambiguous"

    def test_two_names_under_one_numeric_key_are_ambiguous(self, tmp_path):
        renamed = {**F1, "Filer_NamL": "Example for Council 2028"}
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10), contribution(renamed, "a2", 5)],
            "Summary": [summary(F1, "A", "1", 15)],
        }})
        assert _status(ledger, F1, "A")["status"] == "ambiguous"

    def test_pending_filers_are_told_apart_by_name(self, tmp_path):
        one = filing(filer_id="Pending", name="Doe for School Board 2024")
        two = filing(filer_id="Pending", name="Roe for School Board 2024")
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(one, "a1", 10), contribution(two, "a1", 20)],
            "Summary": [summary(one, "A", "1", 10), summary(two, "A", "1", 20)],
        }})
        assert _status(ledger, one, "A")["status"] == "matched"
        assert _status(ledger, two, "A")["status"] == "matched"

    def test_report_num_alone_is_not_a_filing(self, tmp_path):
        later = filing(rpt="2024-03-01", start="2024-01-21", thru="2024-02-20")  # same filer, same Report_Num
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10), contribution(later, "a2", 20)],
            "Summary": [summary(F1, "A", "1", 10), summary(later, "A", "1", 20)],
        }})
        assert len(ledger.filings) == 2
        assert {_status(ledger, f, "A")["status"] for f in (F1, later)} == {"matched"}


class TestMemo:
    def test_a_memo_refno_row_still_counts(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 100),
                                contribution(F1, "a2", 25, Memo_RefNo="a1-note")],
            "Summary": [summary(F1, "A", "1", 125)],
        }})
        assert _status(ledger, F1, "A")["status"] == "matched"
        row = next(r for r in ledger.rows if r.get("tran_id") == "a2")
        assert row["additive"] is True and row["memo_ref"] == "a1-note"

    def test_a_memo_coded_row_is_documented_as_non_additive(self, tmp_path):
        # CAL format: Memo_Code "X" marks an informational entry excluded from the schedule's totals, e.g. a
        # payment made by an agent that is itemized again as the agent's sub-vendor payment.
        ledger = _ledger(tmp_path, {"2024": {
            "E-Expenditure": [expenditure(F1, "e1", 300),
                              expenditure(F1, "e1-sub", 300, Memo_Code="X", Memo_RefNo="e1")],
            "Summary": [summary(F1, "E", "1", 300)],
        }})
        assert _status(ledger, F1, "E")["status"] == "matched"
        memo = next(r for r in ledger.rows if r.get("tran_id") == "e1-sub")
        assert memo["additive"] is False and memo["disposition"] == "retained"


class TestDispositions:
    def test_every_physical_row_has_exactly_one_disposition(self, tmp_path):
        sheets = {
            "A-Contributions": [contribution(F1, "a1", 10), contribution(F1, "a2", 0)],
            "E-Expenditure": [expenditure(F1, "e1", 5)],
            "D-Expenditure": [other(F1, "D-Expenditure", "d1", 999)],
            "B1-Loans": [other(F1, "B1-Loans", "b1", 5000)],
            "497": [{**F1, "Rec_Type": "RCPT", "Form_Type": "F497P1", "Tran_ID": "n1", "Amount": 1500}],
            "Summary": [summary(F1, "A", "1", 10), summary(F1, "E", "1", 5), summary(F1, "D", "1", 999)],
        }
        ledger = _ledger(tmp_path, {"2024": sheets})
        refs = [(r["row_ref"]["sheet"], r["row_ref"]["row"]) for r in ledger.rows]
        assert len(refs) == len(set(refs)) == sum(len(v) for v in sheets.values())
        assert all(r["row_ref"]["file"] == "src/2026-04-14/2024.zip" for r in ledger.rows)
        assert Counter(r["disposition"] for r in ledger.rows) == {"retained": 3, "excluded": 6}
        assert next(r for r in ledger.rows if r["row_ref"]["sheet"] == "A-Contributions")["row_ref"]["row"] == 2

    def test_out_of_scope_sheets_never_enter_a_e_totals(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10)],
            "C-Contributions": [other(F1, "C-Contributions", "c1", 70)],
            "I-Contributions": [other(F1, "I-Contributions", "i1", 80)],
            "D-Expenditure": [other(F1, "D-Expenditure", "d1", 999)],
            "G-Expenditure": [other(F1, "G-Expenditure", "g1", 11)],
            "F-Expenses": [other(F1, "F-Expenses", "f1", 12)],
            "B1-Loans": [other(F1, "B1-Loans", "b1", 5000)],
            "H-Loans": [other(F1, "H-Loans", "h1", 13)],
            "F496P3-Contributions": [other(F1, "F496P3-Contributions", "p1", 14)],
            "F461P5-Expenditure": [other(F1, "F461P5-Expenditure", "p2", 15)],
            "F465P3-Expenditure": [other(F1, "F465P3-Expenditure", "p3", 16)],
            "497": [{**F1, "Rec_Type": "RCPT", "Form_Type": "F497P1", "Tran_ID": "n1", "Amount": 1500}],
            "496": [{**F1, "Rec_Type": "EXPN", "Form_Type": "F496", "Tran_ID": "n2", "Amount": 2500}],
            "Summary": [summary(F1, "A", "1", 10), summary(F1, "E", "1", 0)],
        }})
        assert _status(ledger, F1, "A")["status"] == "matched"
        assert _status(ledger, F1, "E")["status"] == "matched"
        excluded = [r for r in ledger.rows if r["disposition"] == "excluded" and r["row_ref"]["sheet"] != "Summary"]
        assert len(excluded) == 12
        assert all(r["reason"] == "out_of_scope_sheet" and "amount" not in r for r in excluded)

    def test_a_row_of_the_wrong_form_is_rejected(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10), {**contribution(F1, "a2", 99), "Form_Type": "C"}],
            "Summary": [summary(F1, "A", "1", 10)],
        }})
        rejected = [r for r in ledger.rows if r["disposition"] == "rejected"]
        assert [r["reason"] for r in rejected] == ["unexpected_form_type"]
        assert _status(ledger, F1, "A")["status"] == "matched"

    def test_unparseable_amount_is_rejected_and_its_filing_is_not_validated(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10), contribution(F1, "a2", "ten")],
            "Summary": [summary(F1, "A", "1", 10)],
        }})
        assert [r["reason"] for r in ledger.rows if r["disposition"] == "rejected"] == ["unparseable_amount"]
        assert _status(ledger, F1, "A")["validated"] is False


class TestPrivateFields:
    def test_reported_details_are_kept_privately_and_street_never_read(self, tmp_path):
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10, Tran_City="Novato", Tran_State="CA",
                                             Tran_Zip4="94945-1234", Tran_Emp="Example Co", Tran_Occ="Engineer",
                                             Tran_Adr1="SECRET-STREET")],
            "Summary": [summary(F1, "A", "1", 10)],
        }})
        row = _a_e_rows(ledger)[0]
        assert row["reported"] == {"city": "Novato", "state": "CA", "zip5": "94945", "employer": "Example Co",
                                   "occupation": "Engineer"}
        assert "SECRET-STREET" not in repr(row)


class TestSupersession:
    ORIGINAL = filing(report_num="000", rpt="2024-02-01")
    AMENDED = filing(report_num="001", rpt="2024-03-15")

    def _sheets(self):
        return {"2024": {
            "A-Contributions": [contribution(self.ORIGINAL, "a1", 100), contribution(self.AMENDED, "a1", 120)],
            "Summary": [summary(self.ORIGINAL, "A", "1", 100), summary(self.AMENDED, "A", "1", 120)],
        }}

    def test_competing_versions_without_evidence_stay_unresolved(self, tmp_path):
        ledger = _ledger(tmp_path, self._sheets())
        for f in (self.ORIGINAL, self.AMENDED):
            status = _status(ledger, f, "A")
            assert status["status"] == "unresolved_versions" and status["validated"] is False
        assert {r["disposition"] for r in _a_e_rows(ledger)} == {"retained"}

    def test_source_evidence_supersedes_the_original(self, tmp_path):
        probe = build_ledger("src", [])
        original, amended = (probe.filing_id_for(source_id="src", **f) for f in (self.ORIGINAL, self.AMENDED))
        ledger = _ledger(tmp_path, self._sheets(), version_evidence=[{
            "original": original, "amended": amended, "locator": "amended cover page, box 'Amendment #1'",
            "evidence": "cover lists original filing id and the amended Report_Num"}])
        assert _status(ledger, self.ORIGINAL, "A")["status"] == "superseded"
        assert _status(ledger, self.AMENDED, "A")["status"] == "matched"
        old = next(r for r in _a_e_rows(ledger) if r["filing_id"] == original)
        assert old["disposition"] == "superseded" and old["superseded_by"] == amended

    def test_evidence_without_a_locator_is_refused(self, tmp_path):
        probe = build_ledger("src", [])
        original, amended = (probe.filing_id_for(source_id="src", **f) for f in (self.ORIGINAL, self.AMENDED))
        with pytest.raises(LedgerError, match="locator"):
            _ledger(tmp_path, self._sheets(), version_evidence=[{"original": original, "amended": amended,
                                                                 "evidence": "trust me"}])

    def test_a_filer_wide_max_report_num_never_supersedes_another_period(self, tmp_path):
        later = filing(report_num="003", rpt="2024-06-01", start="2024-02-21", thru="2024-05-31")
        ledger = _ledger(tmp_path, {"2024": {
            "A-Contributions": [contribution(self.ORIGINAL, "a1", 100), contribution(later, "a9", 5)],
            "Summary": [summary(self.ORIGINAL, "A", "1", 100), summary(later, "A", "1", 5)],
        }})
        assert _status(ledger, self.ORIGINAL, "A")["status"] == "matched"


class TestWriteLedger:
    def _sheets(self):
        return {"2024": {"A-Contributions": [contribution(F1, "a1", 10, Tran_Zip4="94945")],
                         "Summary": [summary(F1, "A", "1", 10)]}}

    def test_outputs_are_sorted_json_without_timestamps(self, tmp_path):
        from campaign_ledger import write_ledger
        ledger = _ledger(tmp_path, self._sheets())
        write_ledger(ledger, tmp_path / "out")
        names = sorted(p.name for p in (tmp_path / "out").iterdir())
        assert names == ["filings.jsonl", "ledger.jsonl", "reconciliation.json"]
        import json
        recon = json.loads((tmp_path / "out" / "reconciliation.json").read_text())
        assert recon["counts"]["A"]["with_rows"] == {"matched": 1}
        assert recon["dispositions"] == {"excluded": 1, "retained": 1}
        assert recon["physical_rows"] == 2 and recon["errors"] == []

    def test_two_runs_are_byte_identical(self, tmp_path):
        from campaign_ledger import write_ledger
        for run in ("r1", "r2"):
            write_ledger(_ledger(tmp_path / run, self._sheets()), tmp_path / f"out-{run}")
        for name in ("filings.jsonl", "ledger.jsonl", "reconciliation.json"):
            assert (tmp_path / "out-r1" / name).read_bytes() == (tmp_path / "out-r2" / name).read_bytes()
