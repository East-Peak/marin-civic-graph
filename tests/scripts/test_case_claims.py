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
    locator = {"kind": "document", "doc_sha256": sha, "line": 1, "context": "grant of $250,000.00 to the"}
    return claim(locator=locator, **over)


def record_claim(source="ledger", record_id="MF-1", amount="250000.00", **over) -> dict:
    base = {"amount": amount, "locator": {"kind": "record", "source": source, "record_id": record_id, "field": "amount"},
            "derivation": {"kind": "record_field", "script": None, "artifact_sha": None, "recompute": None}}
    return claim(**{**base, **over})


def computed_claim(ledger_sha: str, recompute: dict, amount: str, **over) -> dict:
    return claim(amount=amount, locator={"kind": "record", "source": "ledger", "record_id": "MF-1", "field": "amount"},
                 derivation={"kind": "computed", "script": "s.py", "artifact_sha": ledger_sha, "recompute": recompute},
                 **over)


def _text_claim(tmp, sources, text, context, name="t.txt", **over) -> dict:
    """A claim quoting line 1 of a fresh text document containing `text`."""
    path = tmp / name
    path.write_text(text)
    sha = _sha(path.read_bytes())
    sources["documents"][sha] = str(path)
    row = doc_claim(sha, **over)
    row["locator"] = {"kind": "document", "doc_sha256": sha, "line": 1, "context": context}
    return row


def gap_claim(**over) -> dict:
    base = {"question": "Q3", "amount": None, "precision": "none", "status": "gap", "reconciled": False,
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
        assert not any("0" * 12 in p for p in cc.check_register([doc_claim("0" * 64)], sources))

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
        assert any("not found" in p for p in cc.check_register([record_claim(record_id="MF-9")], sources))
        (tmp / "ledger.jsonl").write_text("{}\n")
        assert any("hash" in p for p in cc.check_register([record_claim()], sources))

    def test_unknown_record_source_fails(self, world):
        _, sources, _, _ = world
        assert any("source" in p for p in cc.check_register([record_claim(source="nope")], sources))

    def test_search_id_must_exist_and_log_rehash(self, world):
        tmp, sources, _, _ = world
        assert any("search_id" in p for p in cc.check_register(
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
        ok["locator"]["context"] = "The Example Fund authorizes a grant of $250,000.00 to the"
        assert cc.check_register([ok], sources) == []
        bad = doc_claim(sha)
        bad["locator"]["context"] = "the example fund authorizes a grant of $250,000.00"
        assert any("context" in p for p in cc.check_register([bad], sources))

    @pytest.mark.parametrize("rendered", ["$250,000", "$250,000.00", "$250000", "$250000.00"])
    def test_currency_renderings_accepted(self, world, rendered):
        tmp, sources, _, _ = world
        text = f"Award of {rendered} approved."
        row = _text_claim(tmp, sources, text, text)
        assert cc.check_register([row], sources) == []

    def test_wrong_cent_fails(self, world):
        _, sources, sha, _ = world
        assert any("amount" in p for p in cc.check_register([doc_claim(sha, amount="250000.01")], sources))

    def test_amount_not_a_substring_of_a_larger_number(self, world):
        tmp, sources, _, _ = world
        text = "Total of $1,250,000.00 approved."
        row = _text_claim(tmp, sources, text, text)
        assert any("amount" in p for p in cc.check_register([row], sources))

    def test_html_is_stripped_and_unescaped(self, world):
        tmp, sources, _, _ = world
        html = "<html><script>var x='$999';</script><body><p>Grant&nbsp;of <b>$250,000.00</b> &amp; more</p></body></html>"
        path = tmp / "page.html"
        path.write_text(html)
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        row = doc_claim(sha)
        row["locator"] = {"kind": "document", "doc_sha256": sha, "line": 1, "context": "Grant of $250,000.00 & more"}
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
        assert any("page" in p for p in cc.check_register([row], sources))  # a whole-PDF search is refused
        row["locator"]["page"] = 0
        assert any("page" in p for p in cc.check_register([row], sources))
        row["locator"]["page"] = 2
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
    def test_gap_and_negative_need_a_search_log_locator_and_no_amount(self, world):
        _, sources, sha, _ = world
        assert cc.check_register([gap_claim(), gap_claim(claim_id="C-Q3-002", status="negative")], sources) == []
        assert cc.check_schema([gap_claim(amount="5.00", precision="approximate")])
        assert cc.check_schema([doc_claim(sha, amount=None, precision="none", status="gap", reconciled=False)])
        rec = record_claim(status="gap", amount=None, precision="none", reconciled=False)
        assert cc.check_schema([rec])

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
        assert cc.check_case_md("## Q1\n### Gaps\n\n## What the records show\nAnything goes.\n", self.ROWS) == []

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


class TestCompatibilityMatrix:
    """Review finding 1: no exact amount may skip its check by pairing the wrong derivation and locator."""

    def test_quoted_derivation_with_a_record_locator_fails(self, world):
        _, sources, _, _ = world
        row = record_claim(amount="999999.99", derivation={"kind": "quoted", "script": None, "artifact_sha": None,
                                                           "recompute": None})
        assert cc.check_register([row], sources)

    def test_record_field_derivation_with_a_document_locator_fails(self, world):
        _, sources, sha, _ = world
        row = doc_claim(sha, derivation={"kind": "record_field", "script": None, "artifact_sha": None,
                                         "recompute": None})
        assert cc.check_register([row], sources)

    def test_partially_documented_exact_amount_on_a_search_log_fails(self, world):
        _, sources, _, _ = world
        row = claim(amount="999.00", status="partially_documented", locator={"kind": "search_log", "search_id": "S-1"},
                    question="Q3")
        assert any("search_log" in p for p in cc.check_register([row], sources))

    def test_invalid_claim_id_is_reported_by_position_only(self, world):
        _, sources, sha, _ = world
        problems = cc.check_register([doc_claim(sha, claim_id="SENTINEL-bad id")], sources)
        assert problems and not any("SENTINEL" in p for p in problems)


class TestLocatorShapes:
    def test_text_document_needs_a_line_not_a_page(self, world):
        tmp, sources, sha, _ = world
        row = doc_claim(sha)
        row["locator"].update(line=None, page=1)
        assert any("line" in p for p in cc.check_register([row], sources))
        row["locator"].update(line=None, page=None)
        assert cc.check_register([row], sources)
        row["locator"].update(line=99)
        assert any("beyond" in p for p in cc.check_register([row], sources))

    def test_line_numbering_counts_non_blank_normalized_lines(self, world):
        tmp, sources, _, _ = world
        row = _text_claim(tmp, sources, "\n\nfirst   line\n\nAward $5.00 here\n", "Award $5.00", amount="5.00")
        assert any("context" in p for p in cc.check_register([row], sources))
        row["locator"]["line"] = 2
        assert cc.check_register([row], sources) == []

    def test_html_lines_follow_block_elements(self, world):
        tmp, sources, _, _ = world
        path = tmp / "p.html"
        path.write_text("<p>Intro</p><p>Award <b>$5.00</b> here</p>")
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        row = doc_claim(sha, amount="5.00")
        row["locator"] = {"kind": "document", "doc_sha256": sha, "line": 2, "context": "Award $5.00 here"}
        assert cc.check_register([row], sources) == []
        row["locator"]["line"] = 1
        assert cc.check_register([row], sources)

    XML = ("<Return xmlns='urn:example'><IRS990ScheduleI><RecipientTable><CashGrantAmt>100</CashGrantAmt>"
           "</RecipientTable><RecipientTable><CashGrantAmt>250000</CashGrantAmt><Note>resolution 250000</Note>"
           "</RecipientTable></IRS990ScheduleI></Return>")

    def _xml_claim(self, tmp, sources, element, context, amount="250000.00"):
        path = tmp / "r.xml"
        path.write_text(self.XML)
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        row = doc_claim(sha, amount=amount)
        row["locator"] = {"kind": "document", "doc_sha256": sha, "element": element, "context": context}
        return row

    def test_xml_element_path_with_index_and_whole_element_number(self, world):
        tmp, sources, _, _ = world
        ok = self._xml_claim(tmp, sources, "IRS990ScheduleI/RecipientTable[2]/CashGrantAmt", "250000")
        assert cc.check_register([ok], sources) == []
        wrong = self._xml_claim(tmp, sources, "IRS990ScheduleI/RecipientTable[1]/CashGrantAmt", "100")
        assert cc.check_register([wrong], sources)  # 100 is not the claimed 250000.00

    def test_xml_bare_number_inside_longer_text_is_refused(self, world):
        tmp, sources, _, _ = world
        row = self._xml_claim(tmp, sources, "RecipientTable[2]/Note", "resolution 250000")
        assert any("amount" in p for p in cc.check_register([row], sources))
        row = self._xml_claim(tmp, sources, "RecipientTable[2]/Note", "250000")
        assert any("context" in p for p in cc.check_register([row], sources))

    def test_xml_ambiguous_or_malformed_path_is_refused(self, world):
        tmp, sources, _, _ = world
        assert any("matches 2" in p for p in cc.check_register(
            [self._xml_claim(tmp, sources, "CashGrantAmt", "250000")], sources))
        assert any("malformed" in p for p in cc.check_register(
            [self._xml_claim(tmp, sources, "A[0]/B", "250000")], sources))


class TestSignedAmounts:
    @pytest.mark.parametrize("rendered, amount, ok", [
        ("-$100.00", "-100.00", True), ("-$100.00", "100.00", False), ("$-100.00", "-100.00", True),
        ("($100.00)", "-100.00", True), ("($100.00)", "100.00", False), ("$100.00", "-100.00", False),
        ("$0.50", "-0.50", False), ("-$0.50", "-0.50", True), ("$0.50", "0.50", True)])
    def test_sign_must_agree(self, world, rendered, amount, ok):
        tmp, sources, _, _ = world
        text = f"Entry of {rendered} noted."
        row = _text_claim(tmp, sources, text, text, amount=amount)
        assert (cc.check_register([row], sources) == []) is ok

    def test_unrelated_bare_number_does_not_support_an_amount(self, world):
        tmp, sources, _, _ = world
        text = "See resolution 250000 for terms."
        assert cc.check_register([_text_claim(tmp, sources, text, text)], sources)

    def test_cents_are_not_truncated(self, world):
        tmp, sources, _, _ = world
        text = "Paid $250,000.99 on file."
        assert cc.check_register([_text_claim(tmp, sources, text, text)], sources)  # claim says 250000.00


class TestSearchLogContents:
    def test_incomplete_log_row_fails(self, world):
        tmp, sources, _, _ = world
        sha = _jsonl(tmp / "searches.jsonl", [{"search_id": "S-1", "question": "Q3"}])
        sources["search_log"]["sha256"] = sha
        assert any("incomplete" in p for p in cc.check_register([gap_claim()], sources))

    def test_blank_field_fails_and_question_must_match(self, world):
        tmp, sources, _, _ = world
        assert any("different question" in p for p in cc.check_register([gap_claim(question="Q5")], sources))
        full = {"search_id": "S-1", "question": "Q3", "source": "a", "query_or_path": "b", "performed_at": "c",
                "result": "d", "stop_reason": "e", "next_step": " "}
        sources["search_log"]["sha256"] = _jsonl(tmp / "searches.jsonl", [full])
        assert any("incomplete" in p for p in cc.check_register([gap_claim()], sources))


class TestCaseMdSentences:
    ROWS = [claim(claim_id="C-Q1-001"), claim(claim_id="C-Q1-002", amount="2400000", precision="approximate",
                                              reconciled=False),
            claim(claim_id="C-Q1-003", amount="-100.00"), claim(claim_id="C-Q1-004", amount=None, precision="none",
                                                                 reconciled=False),
            claim(claim_id="C-Q1-005", amount="900.00")]

    def test_one_citation_does_not_cover_a_second_sentence(self):
        text = "## Q1\nThe grant was approved [C-Q1-004]. A second claim has no source.\n"
        assert any("line 2" in p for p in cc.check_case_md(text, self.ROWS))

    def test_each_sentence_cited_passes_and_wrapped_lines_are_one_sentence(self):
        text = "## Q1\nThe grant was\napproved [C-Q1-004]. And another one [C-Q1-004].\n"
        assert cc.check_case_md(text, self.ROWS) == []

    def test_abbreviations_and_decimals_do_not_split_sentences(self):
        text = "## Q1\nThe U.S. agency cited approx. 2.5 items in Dr. Smith's file [C-Q1-004].\n"
        assert cc.check_case_md(text, self.ROWS) == []

    def test_list_items_are_separate_units(self):
        text = "## Q1\n- first [C-Q1-004]\n- second has none\n"
        assert any("line 3" in p for p in cc.check_case_md(text, self.ROWS))

    def test_factual_subheading_needs_a_citation(self):
        assert any("heading" in p for p in cc.check_case_md("## Q1\n### Total of 5 grants\n", self.ROWS))
        assert cc.check_case_md("## Q1\n### Total of 5 grants [C-Q1-004]\n", self.ROWS) == []

    @pytest.mark.parametrize("heading", ["## Question 1", "# Q1", "## Q 1", "## Q10"])
    def test_nonconforming_answer_headings_are_flagged(self, heading):
        assert any("answer heading" in p for p in cc.check_case_md(f"{heading}\nUncited.\n", self.ROWS))

    def test_signs_and_both_range_endpoints_are_checked(self):
        assert cc.check_case_md("## Notes\nA loss of -$100 [C-Q1-003].\n", self.ROWS) == []
        assert cc.check_case_md("## Notes\nA loss of $-100 and ($100.00) [C-Q1-003].\n", self.ROWS) == []
        assert cc.check_case_md("## Notes\nA gain of $100 [C-Q1-003].\n", self.ROWS)
        assert cc.check_case_md("## Notes\nBetween $-100.00 to $900 [C-Q1-003] [C-Q1-005].\n", self.ROWS) == []
        assert cc.check_case_md("## Notes\nThe range $100-900 [C-Q1-005].\n", self.ROWS)  # $100 unsupported
        assert cc.check_case_md("## Notes\nThe range $900-$100 [C-Q1-005].\n", self.ROWS)

    def test_tolerance_needs_approximation_language(self):
        assert cc.check_case_md("## Notes\nExactly $2M [C-Q1-002].\n", self.ROWS)
        assert cc.check_case_md("## Notes\nThe fund gave $2.4 million [C-Q1-002].\n", self.ROWS)
        for word in ("about", "roughly", "approximately", "nearly", "some", "~"):
            assert cc.check_case_md(f"## Notes\nThe fund gave {word} $2.4 million [C-Q1-002].\n", self.ROWS) == []
        assert cc.check_case_md("## Notes\nThe fund gave about $2M [C-Q1-002].\n", self.ROWS) == []  # within 500k
        assert cc.check_case_md("## Notes\nThe fund gave about $1M [C-Q1-002].\n", self.ROWS)

    def test_bare_suffix_figure_matches_an_exact_claim_exactly(self):
        rows = [claim(claim_id="C-Q1-006", amount="2000000.00")]
        assert cc.check_case_md("## Notes\nGave $2M [C-Q1-006].\n", rows) == []
        assert cc.check_case_md("## Notes\nGave $2.1M [C-Q1-006].\n", rows)


class TestTripwireMasking:
    def test_unmatched_inch_mark_does_not_hide_later_lines(self):
        assert cc.tripwire('A 5" pole.\nA scheme here.\n') == [(2, "scheme")]

    def test_phrase_split_across_a_line_break(self):
        assert cc.tripwire("This was a quid\npro quo.\n") == [(1, "quid pro quo")]

    def test_balanced_quote_in_one_paragraph_does_not_leak_to_the_next(self):
        assert cc.tripwire('"quoted scheme"\n\nlaundering outside\n') == [(3, "laundering")]


class TestRound2:
    ROWS = TestCaseMdSentences.ROWS + [
        claim(claim_id="C-Q1-007", amount="2000000", precision="approximate", reconciled=False),
        claim(claim_id="C-Q1-008", amount="3000000", precision="approximate", reconciled=False),
        claim(claim_id="C-Q1-009", amount="3.00", precision="exact_cents")]

    def test_source_sign_outside_the_context_is_not_dropped(self, world):
        tmp, sources, _, _ = world
        row = _text_claim(tmp, sources, "Entry of -$100.00 noted.", "$100.00 noted", amount="100.00")
        assert any("amount" in p for p in cc.check_register([row], sources))
        row = _text_claim(tmp, sources, "Entry of ($100.00) noted.", "$100.00", amount="100.00", name="u.txt")
        assert any("amount" in p for p in cc.check_register([row], sources))
        row = _text_claim(tmp, sources, "Entry of -$100.00 noted.", "$100.00 noted", amount="-100.00", name="v.txt")
        assert cc.check_register([row], sources) == []

    def test_bare_number_only_as_a_whole_xml_element(self, world):
        tmp, sources, _, _ = world
        row = _text_claim(tmp, sources, "250000", "250000", name="w.txt")  # a line, not an element
        assert any("amount" in p for p in cc.check_register([row], sources))

    @pytest.mark.parametrize("text", ["$2\u2013$3 million", "$2-3 million", "$2 million to $3 million"])
    def test_range_suffix_applies_to_both_endpoints(self, text):
        rows = TestRound2.ROWS
        assert cc.check_case_md(f"## Notes\nAbout {text} [C-Q1-007] [C-Q1-008].\n", rows) == []
        assert cc.check_case_md(f"## Notes\nAbout {text} [C-Q1-009].\n", rows)  # not $2 and $3 exact dollars

    def test_unstructured_subheadings_in_q_sections_need_citations(self):
        assert any("heading" in p for p in cc.check_case_md("## Q1\n### The board approved the grant\n", self.ROWS))
        assert cc.check_case_md("## Q1\n### Sources searched\n#### What the records show\n", self.ROWS) == []

    def test_period_space_capital_ends_a_sentence(self):
        text = "## Q1\nThe grantee was Example Inc. Approved it [C-Q1-004].\n"
        assert any("line 2" in p for p in cc.check_case_md(text, self.ROWS))
        assert cc.check_case_md("## Q1\nSee Dr. Jones and e.g. Mr. Lee on the U.S. board [C-Q1-004].\n",
                                self.ROWS) == []


class TestRound3:
    ROWS = TestRound2.ROWS + [claim(claim_id="C-Q1-010", amount="500.00"), claim(claim_id="C-Q1-011", amount="2000000.00")]

    def test_bare_number_needs_an_amt_element(self, world):
        tmp, sources, _, _ = world
        path = tmp / "c.xml"
        path.write_text("<R><RecipientCnt>250000</RecipientCnt><CashGrantAmt>250000</CashGrantAmt></R>")
        sha = _sha(path.read_bytes())
        sources["documents"][sha] = str(path)
        for element, ok in (("RecipientCnt", False), ("CashGrantAmt", True)):
            row = doc_claim(sha)
            row["locator"] = {"kind": "document", "doc_sha256": sha, "element": element, "context": "250000"}
            assert (cc.check_register([row], sources) == []) is ok

    def test_range_first_endpoint_inherits_suffix_only_when_it_stays_below(self):
        assert cc.check_case_md("## Notes\nAbout $2\u2013$3 million [C-Q1-007] [C-Q1-008].\n", self.ROWS) == []
        assert cc.check_case_md("## Notes\n$500 to $2M [C-Q1-010] [C-Q1-011].\n", self.ROWS) == []

    def test_reversed_range_is_an_error(self):
        problems = cc.check_case_md("## Notes\n$5M to $1M [C-Q1-007].\n", self.ROWS)
        assert any("reversed" in p for p in problems)
