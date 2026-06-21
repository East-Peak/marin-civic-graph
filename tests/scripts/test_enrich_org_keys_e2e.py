"""End-to-end — Identity Enrichment Lane 1 over the real registry facts + the
real 1,346-org export (Unit 5; COMPLETION 4 + 6).

Two halves:

- The real Marin cases prove SURFACE-not-merge (dedup is the LATER milestone):
  once keyed + approved, two existing org refs for Marin Link surface the SAME
  EIN (available to the later dedup run, no merge here); Marin Builders
  Association (c6 → trade_association) and its Scholarship Fund (c3 → charity)
  surface DISTINCT EINs + divergent subtype; San Geronimo Valley CC is keyed.
  These run on the committed BMF slice + constructed approved assertions.

- The real-export pass (gated on the gitignored local files; executed-or-skipped
  for contributors, run for real in the loop) proves the cardinal rule on real
  data: "Marin Link" and "Marin Builders Association" name-match existing nodes
  but are ONLY queued, never auto-merged — and since the real export carries zero
  EINs there are zero deterministic matches and the whole 1,346 is the keyless
  tail, published honestly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from enrich_org_keys import (  # noqa: E402
    build_coverage_report,
    parse_bmf_csv,
    resolve_registry_refs,
)
from export_existing_orgs import org_ref_from_enriched_record  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "identity_enrichment"
BMF_SLICE = FIXTURES / "eo_bmf_marin_slice.csv"
REAL_BMF = REPO_ROOT / "data" / "raw" / "irs-bmf" / "eo_marin.csv"
REAL_EXPORT = REPO_ROOT / "data" / "exports" / "existing-orgs.json"

real_bmf_present = pytest.mark.skipif(
    not REAL_BMF.is_file(), reason="real Marin BMF absent (contributor checkout)"
)
real_export_present = pytest.mark.skipif(
    not REAL_EXPORT.is_file(), reason="real 1,346-org export absent (contributor checkout)"
)

SLICE_BY_EIN = {r["ein"]: r for r in parse_bmf_csv(BMF_SLICE)["refs"]}


def _approved(key_node, existing):
    return make_assertion(
        subject_ref=key_node["id"], target_ref=existing["id"], status="approved",
        basis="operator_approved_ein", subject=key_node, target=existing,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-21", policy_version="v1",
        evidence_refs=key_node["evidence_record_ids"],
    )


def _enriched_ref(existing, key_node, assertion):
    """An existing org's enriched ref after an approved SAME_AS to a key node."""
    record = {
        "id": existing["id"], "display_label": existing["display_label"],
        "own_ein": None, "own_uei": None, "own_source": None,
        "own_irs_subsection_class": None, "degree": 4,
        "key_links": [{
            "linked_node_id": key_node["id"],
            "edge_source_id": key_node["id"], "edge_target_id": existing["id"],
            "assertion_id": assertion["id"], "ein": key_node["ein"], "uei": None,
            "irs_subsection_class": key_node["irs_subsection_class"],
        }],
    }
    return org_ref_from_enriched_record(record, {assertion["id"]: assertion})


# --------------------------------------------------------------------------
# COMPLETION 4 — the real Marin cases SURFACE (no merge here)
# --------------------------------------------------------------------------


def test_marin_link_two_existing_refs_surface_the_same_ein():
    ml = SLICE_BY_EIN["200879422"]
    dup_a = {"id": "org-existing-marin-link", "display_label": "Marin Link"}
    dup_b = {"id": "org-existing-marin-link-inc", "display_label": "Marin Link Inc"}
    ref_a = _enriched_ref(dup_a, ml, _approved(ml, dup_a))
    ref_b = _enriched_ref(dup_b, ml, _approved(ml, dup_b))
    # both surface the SAME EIN — the later dedup run uses this; NO merge here
    assert ref_a["ein"] == "200879422"
    assert ref_b["ein"] == "200879422"
    assert ref_a["id"] != ref_b["id"]  # still two distinct nodes


def test_marin_builders_vs_scholarship_surface_distinct_ein_and_subtype():
    mb = SLICE_BY_EIN["941415040"]
    sf = SLICE_BY_EIN["942540274"]
    mb_ex = {"id": "org-existing-marin-builders", "display_label": "Marin Builders Association"}
    sf_ex = {"id": "org-existing-mb-scholarship", "display_label": "Marin Builders Association Scholarship Fund"}
    ref_mb = _enriched_ref(mb_ex, mb, _approved(mb, mb_ex))
    ref_sf = _enriched_ref(sf_ex, sf, _approved(sf, sf_ex))

    assert ref_mb["ein"] == "941415040"
    assert ref_mb["irs_subsection_class"] == "trade_association"
    assert ref_sf["ein"] == "942540274"
    assert ref_sf["irs_subsection_class"] == "charity"
    # the false-friend pair stays separate — distinct EINs, divergent subtype
    assert ref_mb["ein"] != ref_sf["ein"]
    assert ref_mb["irs_subsection_class"] != ref_sf["irs_subsection_class"]


def test_san_geronimo_valley_cc_keyed():
    sg = SLICE_BY_EIN["237172128"]
    sg_ex = {"id": "org-existing-san-geronimo", "display_label": "San Geronimo Valley Community Center"}
    ref = _enriched_ref(sg_ex, sg, _approved(sg, sg_ex))
    assert ref["ein"] == "237172128"


# --------------------------------------------------------------------------
# COMPLETION 6 — the REAL export: name-queued + keyless tail, zero deterministic
# --------------------------------------------------------------------------


@real_bmf_present
def test_real_bmf_parses_at_scale():
    """The parser handles the full real Marin BMF (2,524 rows) and keys the known
    orgs — real-data coverage of Unit 1 at scale."""
    result = parse_bmf_csv(REAL_BMF)
    by_ein = {r["ein"]: r for r in result["refs"]}
    for ein in ("200879422", "941415040", "942540274", "237172128"):
        assert ein in by_ein, f"expected {ein} keyed from the real BMF"
    assert by_ein["941415040"]["irs_subsection_class"] == "trade_association"
    assert by_ein["942540274"]["irs_subsection_class"] == "charity"
    # every ref is entity_class organization (subtype rides separately)
    assert all(r["entity_class"] == "organization" for r in result["refs"])
    # exactly-9-digit EINs only; subtype never blank
    assert all(len(r["ein"]) == 9 for r in result["refs"])
    assert all(r["irs_subsection_class"] for r in result["refs"])


@real_export_present
def test_real_export_name_queued_never_deterministic():
    """The committed real registry facts resolved against the REAL 1,346-org
    export: a name match (Marin Link, Marin Builders Association) is QUEUED, never
    auto-merged; zero deterministic matches (the export has no EINs); the whole
    export is the keyless tail."""
    existing = json.loads(REAL_EXPORT.read_text())
    registry = list(SLICE_BY_EIN.values())
    result = resolve_registry_refs(registry, existing)

    # the cardinal rule on real data: NOT ONE auto-merge
    assert result["same_as_edges"] == []
    assert result["assertions"] == []
    queued = result["review_candidates"]
    assert all(c["status"] == "queued" for c in queued)
    matched_existing = {c["candidate_ref"] for c in queued}
    assert "org-marin-link" in matched_existing  # name hit, only queued
    assert "org-marin-builders-association" in matched_existing

    report = build_coverage_report({"refs": registry, "skipped": [], "conflicts": []}, result, existing)
    assert report["resolution"]["ein_deterministic_matches"] == 0
    assert report["resolution"]["name_candidates_queued"] >= 2
    assert report["existing_orgs"]["total"] == 1346
    assert report["existing_orgs"]["keyless_tail"] == 1346  # tail published, not implied resolved
