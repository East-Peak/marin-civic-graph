"""Tests for scripts/case_claims.py: the claim-register checker and the CASE.md checks (all values fictional)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import case_claims as cc  # noqa: E402

DOC_TEXT = "Resolution 7. The Example Fund   authorizes a grant of $250,000.00 to the\nSample Housing Agency for FY2027.\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl(path: Path, rows: list[dict]) -> str:
    data = "".join(json.dumps(r) + "\n" for r in rows).encode()
    path.write_bytes(data)
    return _sha(data)


@pytest.fixture()
def world(tmp_path):
    """A document, a ledger, a graph export, a search log, and the sources JSON that pins them."""
    doc = tmp_path / "res7.txt"
    doc.write_text(DOC_TEXT)
    ledger_sha = _jsonl(tmp_path / "ledger.jsonl", [
        {"moneyflow_id": "MF-1", "amount": 250000.0, "filer": "Example Fund PAC"},
        {"moneyflow_id": "MF-2", "amount": "100.50", "filer": "Example Fund PAC"},
        {"moneyflow_id": "MF-3", "amount": 40, "filer": "Other Committee", "meta": {"kind": "A25"}},
    ])
    nodes_sha = _jsonl(tmp_path / "nodes.jsonl", [{"id": "n1", "props": {"amount": "7.25"}}])
    log_sha = _jsonl(tmp_path / "searches.jsonl", [
        {"search_id": "S-1", "question": "Q3", "source": "example", "query_or_path": "x", "performed_at": "2026-10-01",
         "result": "none", "stop_reason": "no rows", "next_step": "records request"}])
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps({"data": {"rows": [{"id": "r1", "amount": 12}]}}))
    sources = {
        "documents": {_sha(doc.read_bytes()): str(doc)},
        "records": {
            "ledger": {"path": str(tmp_path / "ledger.jsonl"), "sha256": ledger_sha, "format": "ledger_jsonl",
                       "id_field": "moneyflow_id"},
            "nodes": {"path": str(tmp_path / "nodes.jsonl"), "sha256": nodes_sha, "format": "graph_nodes_jsonl",
                      "id_field": "id"},
            "rows": {"path": str(rows_path), "sha256": _sha(rows_path.read_bytes()), "format": "json_rows",
                     "id_field": "id", "rows_pointer": "/data/rows"},
        },
        "search_log": {"path": str(tmp_path / "searches.jsonl"), "sha256": log_sha},
    }
    return tmp_path, sources, _sha(doc.read_bytes()), ledger_sha


def claim(**over) -> dict:
    base = {"claim_id": "C-Q1-001", "question": "Q1", "text": "t", "amount": "250000.00", "precision": "exact_cents",
            "locator": None, "derivation": {"kind": "quoted", "script": None, "artifact_sha": None, "recompute": None},
            "status": "documented", "reconciled": True}
    base.update(over)
    return base


def doc_claim(sha: str, **over) -> dict:
    locator = {"kind": "document", "doc_sha256": sha, "page": None, "context": "grant of $250,000.00 to the Sample"}
    return claim(locator=locator, **over)


def record_claim(source="ledger", record_id="MF-1", amount="250000.00", **over) -> dict:
    base = {"amount": amount, "locator": {"kind": "record", "source": source, "record_id": record_id, "field": "amount"},
            "derivation": {"kind": "record_field", "script": None, "artifact_sha": None, "recompute": None}}
    return claim(**{**base, **over})


def computed_claim(ledger_sha: str, recompute: dict, amount: str, **over) -> dict:
    return claim(amount=amount, locator={"kind": "record", "source": "ledger", "record_id": "MF-1", "field": "amount"},
                 derivation={"kind": "computed", "script": "s.py", "artifact_sha": ledger_sha, "recompute": recompute},
                 **over)


def gap_claim(**over) -> dict:
    base = {"amount": None, "precision": "none", "status": "gap", "reconciled": False,
            "locator": {"kind": "search_log", "search_id": "S-1"}}
    return claim(**{**base, **over})


class TestSchema:
    def test_valid_claims_pass(self, world):
        _, sources, sha, _ = world
        assert cc.check_register([doc_claim(sha), gap_claim(claim_id="C-Q3-001")], sources) == []

    @pytest.mark.parametrize("key", ["claim_id", "question", "text", "precision", "locator", "derivation", "status"])
    def test_missing_key_fails(self, world, key):
        _, sources, sha, _ = world
        row = doc_claim(sha)
        del row[key]
        assert any(key in p for p in cc.check_schema([row]))

    def test_enums_fail(self, world):
        _, _, sha, _ = world
        for over in ({"question": "Q7"}, {"precision": "rough"}, {"status": "maybe"}):
            assert cc.check_schema([doc_claim(sha, **over)])

    def test_duplicate_claim_id_fails(self, world):
        _, _, sha, _ = world
        assert any("duplicate" in p for p in cc.check_schema([doc_claim(sha), doc_claim(sha)]))

    @pytest.mark.parametrize("amount", ["250000", "250,000.00", "250000.5", 250000.0, "abc"])
    def test_exact_cents_needs_two_decimals(self, world, amount):
        _, _, sha, _ = world
        assert cc.check_schema([doc_claim(sha, amount=amount)])

    @pytest.mark.parametrize("precision", ["approximate", "projected"])
    def test_approximate_may_carry_amount_but_not_reconciled(self, world, precision):
        _, _, sha, _ = world
        assert cc.check_schema([doc_claim(sha, precision=precision, amount="2500000", reconciled=False)]) == []
        assert any("reconciled" in p for p in cc.check_schema([doc_claim(sha, precision=precision, reconciled=True)]))

    def test_precision_none_needs_null_amount(self, world):
        _, _, sha, _ = world
        assert cc.check_schema([doc_claim(sha, precision="none", reconciled=False)])


class TestLocators:
    def test_unknown_document_sha_fails(self, world):
        _, sources, _, _ = world
        assert any("not in sources" in p for p in cc.check_register([doc_claim("0" * 64)], sources))

    def test_document_bytes_must_rehash(self, world):
        tmp, sources, sha, _ = world
        (tmp / "res7.txt").write_text(DOC_TEXT + "tampered")
        assert any("hash" in p for p in cc.check_register([doc_claim(sha)], sources))

    def test_manifest_resolves_documents(self, world):
        tmp, sources, sha, _ = world
        (tmp / "raw").mkdir()
        (tmp / "raw" / "res7.txt").write_text(DOC_TEXT)
        _jsonl(tmp / "manifest.jsonl", [{"sha256": sha, "path": "res7.txt"}])
        by_manifest = {**sources, "documents": {}, "manifests": [str(tmp / "manifest.jsonl")],
                       "raw_root": str(tmp / "raw")}
        assert cc.check_register([doc_claim(sha)], by_manifest) == []

    def test_record_source_must_rehash_and_record_exist(self, world):
        tmp, sources, _, _ = world
        assert any("MF-9" in p for p in cc.check_register([record_claim(record_id="MF-9")], sources))
        (tmp / "ledger.jsonl").write_text("{}\n")
        assert any("hash" in p for p in cc.check_register([record_claim()], sources))

    def test_unknown_record_source_fails(self, world):
        _, sources, _, _ = world
        assert any("source" in p for p in cc.check_register([record_claim(source="nope")], sources))

    def test_search_id_must_exist_and_log_rehash(self, world):
        tmp, sources, _, _ = world
        assert any("S-9" in p for p in cc.check_register(
            [gap_claim(locator={"kind": "search_log", "search_id": "S-9"})], sources))
        (tmp / "searches.jsonl").write_text("")
        assert any("hash" in p for p in cc.check_register([gap_claim()], sources))

    def test_missing_file_is_a_problem_not_a_crash(self, world):
        tmp, sources, sha, _ = world
        (tmp / "res7.txt").unlink()
        assert cc.check_register([doc_claim(sha)], sources)


class TestDocumentContext:
    def test_context_must_occur_whitespace_normalized_case_sensitive(self, world):
        _, sources, sha, _ = world
        ok = doc_claim(sha)
        ok["locator"]["context"] = "The Example Fund authorizes a grant of $250,000.00 to the Sample"
        assert cc.check_register([ok], sources) == []
        bad = doc_claim(sha)
        bad["locator"]["context"] = "the example fund authorizes a grant of $250,000.00"
        assert any("context" in p for p in cc.check_register([bad], sources))

    @pytest.mark.parametrize("rendered", ["$250,000", "$250,000.00", "250,000", "250000", "250000.00", "250,000.00"])
    def test_standard_renderings_accepted(self, world, rendered):
        tmp, sources, _, _ = world
        text = f"Award of {rendered} approved."
        path = tmp / "r.txt"
        path.write_text(text)
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        row = doc_claim(sha)
        row["locator"] = {"kind": "document", "doc_sha256": sha, "page": None, "context": text}
        assert cc.check_register([row], sources) == []

    def test_wrong_cent_fails(self, world):
        _, sources, sha, _ = world
        assert any("amount" in p for p in cc.check_register([doc_claim(sha, amount="250000.01")], sources))

    def test_amount_not_a_substring_of_a_larger_number(self, world):
        tmp, sources, _, _ = world
        text = "Total of $1,250,000.00 approved."
        path = tmp / "big.txt"
        path.write_text(text)
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        row = doc_claim(sha)
        row["locator"] = {"kind": "document", "doc_sha256": sha, "page": None, "context": text}
        assert any("amount" in p for p in cc.check_register([row], sources))

    def test_html_is_stripped_and_unescaped(self, world):
        tmp, sources, _, _ = world
        html = "<html><script>var x='$999';</script><body><p>Grant&nbsp;of <b>$250,000.00</b> &amp; more</p></body></html>"
        path = tmp / "page.html"
        path.write_text(html)
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        row = doc_claim(sha)
        row["locator"] = {"kind": "document", "doc_sha256": sha, "page": None, "context": "Grant of $250,000.00 & more"}
        assert cc.check_register([row], sources) == []
        row["locator"]["context"] = "var x='$999'"
        row["amount"] = None
        row["precision"] = "none"
        row["reconciled"] = False
        assert any("context" in p for p in cc.check_register([row], sources))

    @pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext not installed")
    def test_pdf_page_specific(self, world):
        tmp, sources, _, _ = world
        path = tmp / "two.pdf"
        path.write_bytes(_two_page_pdf("Alpha page $250,000.00 here", "Beta page only"))
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        row = doc_claim(sha)
        row["locator"] = {"kind": "document", "doc_sha256": sha, "page": 1, "context": "Alpha page $250,000.00 here"}
        assert cc.check_register([row], sources) == []
        row["locator"]["page"] = 2
        assert any("context" in p for p in cc.check_register([row], sources))
        row["locator"] = {"kind": "document", "doc_sha256": sha, "page": None, "context": "Beta page only"}
        row["amount"], row["precision"], row["reconciled"] = None, "none", False
        assert cc.check_register([row], sources) == []


def _two_page_pdf(first: str, second: str) -> bytes:
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>"]
    for i, text in enumerate((first, second)):
        content_id = 4 + 2 * i
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Contents {content_id} 0 R "
                    "/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>")
        stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class TestRecordAndComputed:
    def test_record_field_matches_to_the_cent(self, world):
        _, sources, _, _ = world
        assert cc.check_register([record_claim()], sources) == []  # 250000.0 float
        assert cc.check_register([record_claim(record_id="MF-2", amount="100.50")], sources) == []
        assert any("amount" in p for p in cc.check_register([record_claim(amount="250000.01")], sources))

    def test_record_field_reads_graph_props(self, world):
        _, sources, _, _ = world
        assert cc.check_register([record_claim(source="nodes", record_id="n1", amount="7.25")], sources) == []

    def test_json_rows_pointer(self, world):
        _, sources, _, _ = world
        assert cc.check_register([record_claim(source="rows", record_id="r1", amount="12.00")], sources) == []

    def test_computed_sum_and_count(self, world):
        _, sources, _, sha = world
        total = {"name": "sum", "source": "ledger", "filter": {"filer": "Example Fund PAC"}, "field": "amount"}
        assert cc.check_register([computed_claim(sha, total, "250100.50")], sources) == []
        assert any("recompute" in p for p in cc.check_register([computed_claim(sha, total, "250100.51")], sources))
        count = {"name": "count", "source": "ledger", "filter": {"filer": {"prefix": "Example"}}, "field": "amount"}
        assert cc.check_register([computed_claim(sha, count, "2.00")], sources) == []

    def test_computed_dotted_path_filter(self, world):
        _, sources, _, sha = world
        rc = {"name": "sum", "source": "ledger", "filter": {"meta.kind": "A25"}, "field": "amount"}
        assert cc.check_register([computed_claim(sha, rc, "40.00")], sources) == []

    def test_computed_artifact_sha_must_match_pin(self, world):
        _, sources, _, _ = world
        rc = {"name": "sum", "source": "ledger", "filter": {}, "field": "amount"}
        assert any("artifact_sha" in p for p in cc.check_register([computed_claim("f" * 64, rc, "250140.50")], sources))

    def test_computed_unknown_function_or_missing_recompute_fails(self, world):
        _, sources, _, sha = world
        rc = {"name": "median", "source": "ledger", "filter": {}, "field": "amount"}
        assert cc.check_register([computed_claim(sha, rc, "1.00")], sources)
        assert cc.check_register([computed_claim(sha, None, "1.00")], sources)


class TestStatusRules:
    def test_gap_and_negative_need_absence_locator(self, world):
        _, sources, sha, _ = world
        assert cc.check_register([gap_claim(), gap_claim(claim_id="C-Q3-002", status="negative")], sources) == []
        bad = doc_claim(sha, amount=None, precision="none", status="gap", reconciled=False)
        assert cc.check_register([bad], sources) == []  # a document locator may show the absence
        rec = record_claim(status="gap", amount=None, precision="none", reconciled=False)
        assert any("gap" in p for p in cc.check_register([rec], sources))

    def test_documented_amount_must_not_use_search_log(self, world):
        _, sources, _, _ = world
        row = claim(locator={"kind": "search_log", "search_id": "S-1"})
        assert any("search_log" in p for p in cc.check_register([row], sources))


class TestCaseMd:
    ROWS = [claim(claim_id="C-Q1-001"),
            claim(claim_id="C-Q1-002", amount="2500000", precision="approximate", reconciled=False),
            claim(claim_id="C-Q1-003", amount="1234567.89", precision="projected", reconciled=False),
            claim(claim_id="C-Q1-004", amount=None, precision="none", reconciled=False)]

    def test_clean_document_passes(self):
        text = ("# Case\nIntro with no figure.\n\n## Q1 Grant\nThe grant was $250,000 [C-Q1-001].\n"
                "Roughly ~$2.5M was projected [C-Q1-002].\nA finding [C-Q1-004].\n\n## Notes\nFree text.\n")
        assert cc.check_case_md(text, self.ROWS) == []

    def test_q_section_line_without_citation_fails(self):
        problems = cc.check_case_md("## Q1\nA bare sentence.\n", self.ROWS)
        assert any("line 2" in p for p in problems)

    def test_headings_blank_lines_and_other_sections_exempt(self):
        assert cc.check_case_md("## Q1\n### Sub\n\n## What the records show\nAnything goes.\n", self.ROWS) == []

    def test_cited_but_missing_id_fails(self):
        assert any("C-Q9-999" in p for p in cc.check_case_md("## Q1\nA claim [C-Q9-999].\n", self.ROWS))

    def test_dollar_figure_needs_matching_claim_on_same_line(self):
        assert any("line 2" in p for p in cc.check_case_md("## Notes\nThe fund gave $250,000.\n", self.ROWS))
        assert any("line 2" in p for p in cc.check_case_md("## Notes\nThe fund gave $250,001 [C-Q1-001].\n", self.ROWS))
        assert any("line 2" in p for p in cc.check_case_md("## Notes\nThe fund gave $250,000.\n[C-Q1-001]\n", self.ROWS))
        assert cc.check_case_md("## Notes\nThe fund gave $250,000.00 [C-Q1-001].\n", self.ROWS) == []

    def test_exact_figure_cannot_cite_an_approximate_claim(self):
        assert cc.check_case_md("## Notes\nGave $2,500,000 [C-Q1-002].\n", self.ROWS)

    def test_approximate_figures_need_approximate_claims_within_rounding(self):
        ok = "## Notes\nAbout $2.5 million [C-Q1-002]. And approximately $1.2M [C-Q1-003]. And ~$2,500,000 [C-Q1-002].\n"
        assert cc.check_case_md(ok, self.ROWS) == []
        assert cc.check_case_md("## Notes\nAbout $2.6 million [C-Q1-002].\n", self.ROWS)
        assert cc.check_case_md("## Notes\nAbout $250,000 [C-Q1-001].\n", self.ROWS)  # exact claim, approx figure

    def test_figures_in_headings_and_preamble_are_checked(self):
        assert cc.check_case_md("# A $5 title\n", self.ROWS)


class TestTripwire:
    def test_flags_outside_quotes_with_prefix_matching(self):
        hits = cc.tripwire("Plain.\nThis was laundering and corruption.\nA Quid  Pro Quo too.\n")
        assert hits == [(2, "laundering"), (2, "corruption"), (3, "quid pro quo")]

    def test_quotes_and_blockquotes_pass(self):
        text = 'He said "this is a scheme" and “kickback” too.\n> a payoff quoted\n  > patronage\nOK.\n'
        assert cc.tripwire(text) == []

    def test_quote_state_spans_lines_but_resets_at_blank_line(self):
        assert cc.tripwire('"a long quote\nabout favoritism"\n') == []
        assert cc.tripwire('An "unbalanced quote\n\nthen deadbeat here\n') == [(3, "deadbeat")]

    def test_word_outside_after_closing_quote_is_flagged(self):
        assert cc.tripwire('"fine" but scheme\n') == [(1, "scheme")]


class TestCli:
    def _write(self, tmp, rows, sources):
        reg, src = tmp / "reg.jsonl", tmp / "src.json"
        _jsonl(reg, rows)
        src.write_text(json.dumps(sources))
        return ["--register", str(reg), "--sources", str(src)]

    def test_clean_run_exits_zero(self, world, capsys):
        tmp, sources, sha, _ = world
        assert cc.main(self._write(tmp, [doc_claim(sha)], sources)) == 0
        assert "1 claims, 0 problems" in capsys.readouterr().out

    def test_problems_exit_one_without_claim_text(self, world, capsys):
        tmp, sources, sha, _ = world
        row = doc_claim(sha, amount="250000.01", text="SENTINEL-CLAIM-TEXT")
        assert cc.main(self._write(tmp, [row], sources)) == 1
        out = capsys.readouterr().out
        assert "1 claims, 1 problems" in out and "C-Q1-001" in out and "SENTINEL-CLAIM-TEXT" not in out

    def test_case_md_and_tripwire_fail_the_run(self, world, capsys):
        tmp, sources, sha, _ = world
        md = tmp / "CASE.md"
        md.write_text("## Q1\nA scheme [C-Q1-001].\n")
        assert cc.main(self._write(tmp, [doc_claim(sha)], sources) + ["--case-md", str(md)]) == 1
        assert "tripwire" in capsys.readouterr().out
