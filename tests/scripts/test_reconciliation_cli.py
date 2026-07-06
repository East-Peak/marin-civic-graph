"""Goal 1 Unit 8 — the read-model orchestrator + CLI: collapse precomputed candidate
artifacts (+ ledger + verdicts) into the versioned read model JSONL + a coverage report.
"""
from __future__ import annotations

import json
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconciliation_read_model as rm  # noqa: E402
from reconciliation_registry import ANCHOR_PREFIX_BY_SOURCE, KEY_FIELD_BY_SOURCE, KEY_SOURCES  # noqa: E402
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


def test_detect_source_and_adapter_maps_are_registry_derived():
    assert set(rm._ADAPTERS_BY_SOURCE) == set(KEY_SOURCES)
    assert rm._KEY_FIELD_BY_SOURCE == KEY_FIELD_BY_SOURCE
    for source, field in KEY_FIELD_BY_SOURCE.items():
        assert rm.detect_source({"subject_ref": "org-not-an-anchor", field: "public-key"}) == source
    for source, prefix in ANCHOR_PREFIX_BY_SOURCE.items():
        assert rm.detect_source({"subject_ref": f"{prefix}123"}) == source
    source = inspect.getsource(rm.detect_source)
    assert "registry_ein" not in source
    assert "committee_id" not in source


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


def test_cli_verdict_feed_conflicts_fail_loud(tmp_path):
    cf = tmp_path / "cands.jsonl"
    cf.write_text(json.dumps(EIN_RAW) + "\n", encoding="utf-8")
    vf = tmp_path / "verdicts.jsonl"
    first = {
        "schema_version": "verdict-feed-v1",
        "vendor_id": "org-marincontract-recipient-x",
        "proposed_key": "953667812",
        "verdict": "same",
        "confidence": 0.95,
        "provenance": {"model": "unit", "run": "r5"},
    }
    second = {**first, "verdict": "different"}
    vf.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    out = tmp_path / "rm.jsonl"

    with pytest.raises(ValueError, match="conflicting verdict feed duplicate"):
        rm.main(["--candidates", str(cf), "--verdicts", str(vf), "--out", str(out)])
    assert not out.exists()


def test_cli_explicit_missing_ledger_fails_loud(tmp_path):
    cf = tmp_path / "cands.jsonl"
    cf.write_text(json.dumps(EIN_RAW) + "\n", encoding="utf-8")
    out = tmp_path / "rm.jsonl"
    with pytest.raises(FileNotFoundError, match="ledger path"):
        rm.main([
            "--candidates", str(cf),
            "--ledger", str(tmp_path / "typoed-ledger.jsonl"),
            "--out", str(out),
        ])
    assert not out.exists()


# --- Unit 2: review_flags + bulk_eligible + per-key AI matching ------------

SOS_EXACT = {**SOS_RAW, "signals": ["normalized_name_exact"], "needs_careful_review": False}


def _verdict(vendor, key, verdict="same", conf=0.95):
    return {"vendor_id": vendor, "proposed_key": key, "verdict": verdict, "confidence": conf, "reason": "x"}


def test_ein_single_exact_keymatched_same_is_bulk_eligible():
    cases = rm.build_attach_read_model(
        [EIN_RAW], verdict_rows=[_verdict("org-marincontract-recipient-x", "953667812", conf=0.95)])
    c = cases[0]
    assert c.review_flags == {}                 # EIN has no careful-review concept
    assert c.bulk_eligible is True


def test_bulk_ineligible_ai_below_threshold():
    cases = rm.build_attach_read_model(
        [EIN_RAW], verdict_rows=[_verdict("org-marincontract-recipient-x", "953667812", conf=0.8)])
    assert cases[0].bulk_eligible is False


def test_bulk_ineligible_ai_same_for_different_key():
    # the only "same" verdict is for a DIFFERENT proposed_key → must not count, no review attached
    cases = rm.build_attach_read_model(
        [EIN_RAW], verdict_rows=[_verdict("org-marincontract-recipient-x", "999999999", conf=0.99)])
    assert cases[0].ai_reviews == []
    assert cases[0].bulk_eligible is False


def test_bulk_ineligible_non_exact_signal():
    # SOS_RAW has name_similarity (fuzzy), not normalized_name_exact
    cases = rm.build_attach_read_model(
        [SOS_RAW], verdict_rows=[_verdict("org-marincontract-recipient-y", "0289793", conf=0.99)])
    assert cases[0].bulk_eligible is False


def test_sos_needs_careful_review_surfaced_and_blocks_bulk():
    careful = {**SOS_EXACT, "needs_careful_review": True}
    cases = rm.build_attach_read_model(
        [careful], verdict_rows=[_verdict("org-marincontract-recipient-y", "0289793", conf=0.99)])
    assert cases[0].review_flags == {"needs_careful_review": True}
    assert cases[0].bulk_eligible is False


def test_sos_exact_not_careful_is_bulk_eligible():
    cases = rm.build_attach_read_model(
        [SOS_EXACT], verdict_rows=[_verdict("org-marincontract-recipient-y", "0289793", conf=0.97)])
    assert cases[0].review_flags == {"needs_careful_review": False}
    assert cases[0].bulk_eligible is True


def test_bulk_ineligible_when_vendor_has_multiple_candidates_for_source():
    e2 = {**EIN_RAW, "subject_ref": "org-bmf-ein-111111111"}
    cases = rm.build_attach_read_model(
        [EIN_RAW, e2], verdict_rows=[_verdict("org-marincontract-recipient-x", "953667812", conf=0.99)])
    assert all(c.bulk_eligible is False for c in cases)  # not a single candidate for the vendor


def test_schema_version_bumped_and_additive():
    import reconciliation_cases as rc
    assert rc.SCHEMA_VERSION == "recon-read-model-v2"
    # additive: a case still serializes all pre-existing fields + the two new ones
    row = rm.build_case_row(rm.build_attach_read_model([EIN_RAW])[0])
    for k in ("schema_version", "case_id", "case_type", "candidate_joins", "actionability",
              "current_ledger_status", "ledger_assertion_refs", "ai_reviews", "graph_context_refs"):
        assert k in row
    assert "review_flags" in row and "bulk_eligible" in row
