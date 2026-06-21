"""Tests for scripts/enrich_org_keys.py — Unit 2: resolution wiring.

Lane 1, Unit 2 (Predeclared 3). Registry refs go through the SHARED resolver
(`propose_org_resolutions`, identity_keys=("ein","uei")) and Identity Control A's
egress gate. The cardinal rule is the point of the negative tests: an EIN match
is deterministic; a NAME (even with a matching city) is only ever a QUEUED
candidate — never an auto-merge.

Pinned contracts:
- review/enrichment artifacts carry `signal_strength`, NEVER `confidence`
  (via the adapter), plus the registry city/subsection/EIN as REVIEW EVIDENCE
  so the operator approves against the hard key + locale, not a bare name;
- city is corroboration on the packet, NEVER an auto-approver;
- when this lane writes a ledger assertion for an approved candidate, the
  candidate's `evidence_record_ids` map to `make_assertion(evidence_refs=...)`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from enrich_org_keys import (  # noqa: E402
    assertion_for_approved_candidate,
    bmf_org_ref,
    enrich_review_candidate,
    resolve_registry_refs,
)

MARIN_BUILDERS_ROW = {
    "EIN": "941415040",
    "NAME": "MARIN BUILDERS ASSOCIATION",
    "CITY": "SAN RAFAEL",
    "STATE": "CA",
    "SUBSECTION": "06",
}


# --------------------------------------------------------------------------
# Deterministic path — a matching EIN on a CONSTRUCTED keyed existing-org
# fixture (the real export has zero EINs — COMPLETION 2a)
# --------------------------------------------------------------------------


def test_matching_ein_yields_deterministic_assertion():
    registry = [bmf_org_ref(MARIN_BUILDERS_ROW)]
    existing_keyed = [
        {
            "id": "org-existing-marin-builders",
            "display_label": "Marin Builders Association",
            "ein": "941415040",  # constructed: the existing node already carries the EIN
        }
    ]
    result = resolve_registry_refs(registry, existing_keyed)

    assert len(result["same_as_edges"]) == 1
    edge = result["same_as_edges"][0]
    assert edge["relationship_type"] == "SAME_AS"
    assert edge["properties"]["basis"] == "ein_exact"
    # egress-gated: the edge is stamped with its deterministic assertion id
    assert edge["properties"]["assertion_id"].startswith("assertion-")

    assert len(result["assertions"]) == 1
    assertion = result["assertions"][0]
    assert assertion["status"] == "deterministic"
    assert assertion["basis"] == "ein_exact"
    assert assertion["id"] == edge["properties"]["assertion_id"]


# --------------------------------------------------------------------------
# Name path — the cardinal rule: a name (even a name+city) is QUEUED, never
# auto-merged (COMPLETION 2b shape on a constructed no-EIN existing list)
# --------------------------------------------------------------------------


def test_no_ein_existing_org_is_name_queued_never_deterministic():
    registry = [bmf_org_ref(MARIN_BUILDERS_ROW)]
    existing_no_key = [
        {
            "id": "org-existing-marin-builders",
            "display_label": "Marin Builders Association",
            # NO ein — like every node in the real 1,346-org export
        }
    ]
    result = resolve_registry_refs(registry, existing_no_key)

    assert result["same_as_edges"] == []
    assert result["assertions"] == []
    queued = result["review_candidates"]
    assert len(queued) == 1
    assert queued[0]["status"] == "queued"
    assert queued[0]["subject_ref"] == "org-bmf-ein-941415040"
    assert queued[0]["candidate_ref"] == "org-existing-marin-builders"


def test_city_match_is_corroboration_not_an_auto_approver():
    """A name match whose registry city equals the existing org's city is STILL
    only queued — locale corroborates the review packet, it never merges."""
    registry = [bmf_org_ref(MARIN_BUILDERS_ROW)]  # San Rafael
    existing = [
        {
            "id": "org-existing-marin-builders",
            "display_label": "Marin Builders Association",
            "city": "San Rafael",
        }
    ]
    result = resolve_registry_refs(registry, existing)
    assert result["same_as_edges"] == []
    assert all(c["status"] == "queued" for c in result["review_candidates"])


# --------------------------------------------------------------------------
# The review-artifact wrapper — signal_strength + registry evidence
# --------------------------------------------------------------------------


def test_review_candidate_carries_signal_strength_and_registry_evidence():
    registry = [bmf_org_ref(MARIN_BUILDERS_ROW)]
    registry_by_id = {r["id"]: r for r in registry}
    raw_candidate = {
        "subject_ref": "org-bmf-ein-941415040",
        "candidate_ref": "org-existing-marin-builders",
        "signals": ["normalized_name_exact"],
        "confidence": 0.9,
        "status": "queued",
        "evidence_record_ids": ["record-bmf-941415040"],
    }
    enriched = enrich_review_candidate(raw_candidate, registry_by_id)

    # confidence renamed to signal_strength (never a calibrated probability)
    assert enriched["signal_strength"] == 0.9
    assert "confidence" not in enriched
    # registry locale + subtype + key attached as REVIEW evidence
    assert enriched["registry_city"] == "San Rafael"
    assert enriched["registry_state"] == "CA"
    assert enriched["registry_irs_subsection_class"] == "trade_association"
    assert enriched["registry_ein"] == "941415040"


# --------------------------------------------------------------------------
# Approved-candidate ledger write — evidence_record_ids -> evidence_refs
# (Predeclared 3, the pinned Codex r2 mapping)
# --------------------------------------------------------------------------


def test_approved_candidate_maps_evidence_record_ids_to_evidence_refs():
    candidate = {
        "subject_ref": "org-bmf-ein-941415040",
        "candidate_ref": "org-existing-marin-builders",
        "signals": ["normalized_name_exact"],
        "signal_strength": 0.9,
        "status": "queued",
        "evidence_record_ids": ["record-bmf-941415040"],
    }
    subject = {"id": "org-bmf-ein-941415040", "display_label": "Marin Builders Association", "ein": "941415040"}
    target = {"id": "org-existing-marin-builders", "display_label": "Marin Builders Association"}

    assertion = assertion_for_approved_candidate(
        candidate,
        subject=subject,
        target=target,
        basis="operator_approved_ein",
        reviewer="stuart@eastpeak.cc",
        decided_at="2026-06-21",
    )
    assert assertion["status"] == "approved"
    assert assertion["basis"] == "operator_approved_ein"
    # the candidate's evidence_record_ids flowed into the ledger's evidence_refs
    assert assertion["evidence_refs"] == ["record-bmf-941415040"]
    assert assertion["subject_ref"] == "org-bmf-ein-941415040"
    assert assertion["target_ref"] == "org-existing-marin-builders"
