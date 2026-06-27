"""Goal 1 Unit 8 — the read-model orchestrator + CLI: collapse precomputed candidate
artifacts (+ ledger + verdicts) into the versioned read model JSONL + a coverage report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconciliation_read_model as rm  # noqa: E402
from enrich_casos_keys import scan_for_forbidden  # noqa: E402

EIN_RAW = {"subject_ref": "org-bmf-ein-953667812", "candidate_ref": "org-marincontract-recipient-x",
           "vendor_ref": "org-marincontract-recipient-x", "signals": ["normalized_name_exact"],
           "signal_strength": 0.9, "registry_ein": "953667812", "registry_city": "San Rafael",
           "registry_state": "CA", "registry_irs_subsection_class": "charity", "display_label": "EX YOUTH"}
SOS_RAW = {"subject_ref": "org-casos-0289793", "candidate_ref": "org-marincontract-recipient-y",
           "vendor_ref": "org-marincontract-recipient-y", "signals": ["name_similarity:0.88"],
           "confidence": 0.88, "sos_ref": {"sos_id": "0289793", "display_label": "Example LLC",
           "entity_type": "LLC", "entity_status": "active", "formation_date": "2001-01-01",
           "principal_city": "San Rafael", "principal_state": "CA"}, "display_label": "EX SERVICES"}
FPPC_RAW = {"subject_ref": "org-fppc-1470249", "candidate_ref": "org-example-committee",
            "committee_id": "1470249", "signals": ["name_similarity:0.9"], "confidence": 0.9,
            "display_label": "Example for Council 2024"}


def test_detect_source():
    assert rm.detect_source(EIN_RAW) == "ein"
    assert rm.detect_source(SOS_RAW) == "sos_id"
    assert rm.detect_source(FPPC_RAW) == "committee_id"
    with pytest.raises(ValueError, match="detect"):
        rm.detect_source({"subject_ref": "org-mystery-1"})


def test_build_attach_read_model_collapses_all_three_shapes():
    cases = rm.build_attach_read_model([EIN_RAW, SOS_RAW, FPPC_RAW])
    assert len(cases) == 3
    assert all(c.case_type == "identity_key_attach" for c in cases)
    assert {c.candidate_joins[0].left_ref.source_id for c in cases} == {"ein", "sos_id", "committee_id"}
    assert all(c.current_ledger_status == "none" for c in cases)  # no ledger supplied


def test_ai_reviews_attached_by_vendor():
    verdicts = [{"vendor_id": "org-marincontract-recipient-x", "proposed_key": "953667812",
                 "verdict": "same", "confidence": 0.9, "reason": "exact"}]
    cases = rm.build_attach_read_model([EIN_RAW], verdict_rows=verdicts)
    assert cases[0].ai_reviews and cases[0].ai_reviews[0]["verdict"] == "same"


def test_coverage_counts():
    cov = rm.coverage(rm.build_attach_read_model([EIN_RAW, SOS_RAW]))
    assert cov["cases"] == 2
    assert cov["by_case_type"]["identity_key_attach"] == 2


def test_cli_writes_read_model_and_coverage(tmp_path):
    cf = tmp_path / "cands.jsonl"
    cf.write_text("\n".join(json.dumps(r) for r in [EIN_RAW, SOS_RAW, FPPC_RAW]))
    vf = tmp_path / "verdicts.jsonl"
    vf.write_text(json.dumps({"vendor_id": "org-marincontract-recipient-x", "proposed_key": "953667812",
                              "verdict": "same", "confidence": 0.9, "reason": "ok"}))
    out = tmp_path / "rm.jsonl"
    rc = rm.main(["--candidates", str(cf), "--verdicts", str(vf), "--out", str(out)])
    assert rc == 0
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert len(rows) == 3
    cov = json.loads(out.with_suffix(".coverage.json").read_text())
    assert cov["cases"] == 3
    assert scan_for_forbidden(rows) == []  # the written read model is leak-clean
