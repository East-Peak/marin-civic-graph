"""Goal 1 Unit 2 — reconciliation adapters normalize PRECOMPUTED candidate artifacts
into CandidateJoins (EntityRef ↔ EntityRef + signal_strength). They do NOT rerun raw
source scans. Synthetic rows match the real lane shapes: EIN (signal_strength + flat
registry_*), county SOS (confidence + nested sos_ref), FPPC (confidence + committee_id).
The normalized output carries no `confidence` and every join has EntityRefs + signal_strength.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconciliation_adapters as ra  # noqa: E402
import reconciliation_cases as rc  # noqa: E402

EIN_RAW = {
    "subject_ref": "org-bmf-ein-953667812", "candidate_ref": "org-marincontract-recipient-x",
    "vendor_ref": "org-marincontract-recipient-x", "ein_anchor_ref": "org-bmf-ein-953667812",
    "signals": ["normalized_name_exact"], "signal_strength": 0.9, "registry_ein": "953667812",
    "registry_city": "San Rafael", "registry_state": "CA", "registry_irs_subsection_class": "charity",
    "display_label": "EXAMPLE YOUTH PROGRAMS",
}
SOS_RAW = {
    "subject_ref": "org-casos-0289793", "candidate_ref": "org-marincontract-recipient-y",
    "vendor_ref": "org-marincontract-recipient-y", "sos_anchor_ref": "org-casos-0289793",
    "signals": ["name_similarity:0.88"], "confidence": 0.88,
    "sos_ref": {"sos_id": "0289793", "display_label": "Example Services LLC", "entity_type": "LLC",
                "entity_status": "active", "formation_date": "2001-01-01",
                "principal_city": "San Rafael", "principal_state": "CA"},
    "individual_agent": True, "needs_careful_review": False, "display_label": "EXAMPLE SERVICES",
}
FPPC_RAW = {
    "subject_ref": "org-fppc-1470249", "candidate_ref": "org-example-committee",
    "committee_id": "1470249", "signals": ["name_similarity:0.9"], "confidence": 0.9,
    "display_label": "Example for Council 2024",
}


def _adapters():
    return [ra.EinAdapter([EIN_RAW]), ra.SosAdapter([SOS_RAW]), ra.CommitteeAdapter([FPPC_RAW])]


def test_interface_methods_present():
    for a in _adapters():
        for m in ("emit_refs", "emit_candidates", "coverage_report", "redaction_policy"):
            assert callable(getattr(a, m)), f"{type(a).__name__} missing {m}"


def test_each_join_has_entity_refs_and_signal_strength():
    for a in _adapters():
        joins = a.emit_candidates(existing_refs=[])
        assert joins, type(a).__name__
        for j in joins:
            assert isinstance(j, rc.CandidateJoin)
            assert isinstance(j.left_ref, rc.EntityRef)
            assert isinstance(j.right_ref, rc.EntityRef)
            assert isinstance(j.signal_strength, float)


def test_confidence_mapped_to_signal_strength():
    sos_join = ra.SosAdapter([SOS_RAW]).emit_candidates(existing_refs=[])[0]
    assert sos_join.signal_strength == 0.88  # mapped from confidence
    fppc_join = ra.CommitteeAdapter([FPPC_RAW]).emit_candidates(existing_refs=[])[0]
    assert fppc_join.signal_strength == 0.9
    ein_join = ra.EinAdapter([EIN_RAW]).emit_candidates(existing_refs=[])[0]
    assert ein_join.signal_strength == 0.9  # already signal_strength


def test_no_confidence_anywhere_in_normalized_output():
    for a in _adapters():
        for j in a.emit_candidates(existing_refs=[]):
            blob = json.dumps(dataclasses.asdict(j))
            assert "confidence" not in blob, f"{type(a).__name__} leaked 'confidence'"


def test_sos_right_ref_carries_publishable_fields_only():
    j = ra.SosAdapter([SOS_RAW]).emit_candidates(existing_refs=[])[0]
    keys = set(j.right_ref.public_fields)
    assert keys <= {"sos_id", "display_label", "entity_type", "entity_status",
                    "formation_date", "principal_city", "principal_state"}
    # no agent/address fields ever
    assert not any("address" in k or "agent" in k for k in keys)


def test_redaction_policy_declared():
    for a in _adapters():
        pol = a.redaction_policy()
        assert {"public_fields", "forbidden_fields", "pii_class"} <= set(pol)
        assert isinstance(pol["public_fields"], (list, tuple))


def test_coverage_report_counts():
    assert ra.EinAdapter([EIN_RAW]).coverage_report()["candidates"] == 1
    assert ra.SosAdapter([]).coverage_report()["candidates"] == 0
