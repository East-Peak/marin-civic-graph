"""Tests for scripts/enrich_casos_keys.py — Lane 2 Unit 3: resolution wiring.

The deterministic path (a matching sos_id on BOTH sides → an egress-gated
`deterministic` ledger assertion — the ONE permitted auto-merge), the name path
(the real state — existing orgs carry no sos_id → queued, never auto-merged), the
review-evidence wrapper (SOS status/type/city attached so the operator approves
against the hard entity number + Novato-vs-Stockton locale, never a bare name),
and the pinned evidence mapping (candidate `evidence_record_ids` →
`make_assertion(evidence_refs=...)`). No raw SOS row is carried as review/ledger data.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from enrich_casos_keys import (  # noqa: E402
    assertion_for_approved_casos_candidate,
    block_casos_against_existing,
    enrich_casos_candidate,
    resolve_casos_deterministic,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity_enrichment_casos"
FILINGS_SLICE = FIXTURES / "filings_slice.csv"


GCC_REF = {
    "id": "org-casos-1819837",
    "display_label": "Ghilotti Construction Company, Inc.",
    "sos_id": "1819837",
    "entity_class": "organization",
    "entity_status": "Active",
    "entity_type": "Stock Corporation - CA - General",
    "formation_date": "04/23/1992",
    "principal_city": "Santa Rosa",
    "principal_state": "CA",
    "evidence_record_ids": ["record-casos-1819837"],
}


# --------------------------------------------------------------------------
# Deterministic path — matching sos_id on a CONSTRUCTED keyed existing org
# --------------------------------------------------------------------------


def test_matching_sos_id_yields_deterministic_assertion():
    existing_keyed = [{
        "id": "org-existing-ghilotti-construction-company",
        "display_label": "Ghilotti Construction Company",
        "sos_id": "1819837",
    }]
    result = resolve_casos_deterministic([GCC_REF], existing_keyed)

    assert len(result["same_as_edges"]) == 1
    edge = result["same_as_edges"][0]
    assert edge["properties"]["basis"] == "sos_id_exact"
    assert edge["properties"]["assertion_id"].startswith("assertion-")

    assert len(result["assertions"]) == 1
    a = result["assertions"][0]
    assert a["status"] == "deterministic"
    assert a["basis"] == "sos_id_exact"
    assert a["id"] == edge["properties"]["assertion_id"]


def test_no_sos_id_existing_is_name_queued_never_deterministic():
    existing_no_key = [{
        "id": "org-existing-ghilotti-construction-company",
        "display_label": "Ghilotti Construction Company",
    }]
    result = resolve_casos_deterministic([GCC_REF], existing_no_key)
    assert result["same_as_edges"] == []
    assert result["assertions"] == []
    assert all(c["status"] == "queued" for c in result["candidates"])


# --------------------------------------------------------------------------
# Review-evidence wrapper
# --------------------------------------------------------------------------


def test_enrich_candidate_attaches_status_type_city_not_raw_rows():
    candidate = {
        "subject_ref": "org-casos-1628638",
        "candidate_ref": "org-miller-pacific-engineering-group",
        "sos_id": "1628638",
        "signals": ["normalized_name_exact"],
        "signal_strength": 0.9,
        "status": "queued",
        "entity_status": "Active",
        "evidence_record_ids": ["record-casos-1628638"],
    }
    ref = {
        "entity_status": "Active", "entity_type": "Stock Corporation - CA - General",
        "formation_date": "05/03/1991", "principal_city": "Novato", "principal_state": "CA",
    }
    out = enrich_casos_candidate(candidate, ref)
    assert out["signal_strength"] == 0.9 and "confidence" not in out
    assert out["registry_entity_type"] == "Stock Corporation - CA - General"
    assert out["registry_formation_date"] == "05/03/1991"
    assert out["registry_principal_city"] == "Novato"  # the Novato-vs-Stockton disambiguator
    # no street/ZIP/person ever rides along
    assert not any("REDACT" in str(v) for v in out.values())
    assert not any("address" in k.lower() or "postal" in k.lower() for k in out)


def test_block_candidates_carry_review_evidence():
    existing = [{"id": "org-mpeg", "display_label": "Miller Pacific Engineering Group"}]
    result = block_casos_against_existing(FILINGS_SLICE.read_text().splitlines(), existing)
    novato = [c for c in result["candidates"] if c["sos_id"] == "1628638"][0]
    assert novato["registry_principal_city"] == "Novato"
    assert novato["registry_entity_status"] == "Active" or novato["entity_status"] == "Active"


# --------------------------------------------------------------------------
# Approved-candidate ledger write — evidence_record_ids -> evidence_refs
# --------------------------------------------------------------------------


def test_approved_candidate_maps_evidence_record_ids_to_evidence_refs():
    candidate = {
        "subject_ref": "org-casos-1819837",
        "candidate_ref": "org-existing-gcc",
        "signals": ["significant_token_overlap"],
        "signal_strength": 0.5,
        "status": "queued",
        "evidence_record_ids": ["record-casos-1819837"],
    }
    subject = GCC_REF
    target = {"id": "org-existing-gcc", "display_label": "Ghilotti Construction"}
    a = assertion_for_approved_casos_candidate(
        candidate, subject=subject, target=target,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-21",
    )
    assert a["status"] == "approved"
    assert a["basis"] == "operator_approved_sos_id"
    assert a["evidence_refs"] == ["record-casos-1819837"]
    assert a["subject_ref"] == "org-casos-1819837"
    assert a["target_ref"] == "org-existing-gcc"
