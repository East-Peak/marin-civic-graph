"""End-to-end — Identity Enrichment Lane 2 over the real staged CA SOS Filings
file + the real for-profit vendor labels (Unit 7; COMPLETION 4b + 6).

Executed-or-skipped: gated on the gitignored local `data/raw/ca-sos/Filings.csv`
(9.44M rows) + the real export. The block streams the whole file once (~60s) — a
module-scoped fixture so it runs once. Proves the real Ghilotti / Miller Pacific
(Novato 1628638, NOT the Stockton 1539723 false friend) / Cumming cases surface as
queued candidates carrying their entity number + city; that an operator approval
makes the enriched export surface exactly that sos_id; and that NO person/address
data reaches any artifact.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from org_resolution import KEY_NORMALIZERS  # noqa: E402
from enrich_casos_keys import (  # noqa: E402
    block_casos_against_existing,
    build_casos_coverage_report,
    scan_for_forbidden,
)
from export_existing_orgs import write_enriched_orgs  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402

REAL_FILINGS = REPO_ROOT / "data" / "raw" / "ca-sos" / "Filings.csv"
REAL_EXPORT = REPO_ROOT / "data" / "exports" / "existing-orgs.json"

real_present = pytest.mark.skipif(
    not (REAL_FILINGS.is_file() and REAL_EXPORT.is_file()),
    reason="real CA-SOS Filings.csv / 1,346-org export absent (contributor checkout)",
)

# The real for-profit vendor labels (from the export) + their true SOS entity.
FORPROFIT = [
    {"id": "org-ghilotti-construction", "display_label": "Ghilotti Construction"},
    {"id": "org-ghilotti-construction-company", "display_label": "Ghilotti Construction Company"},
    {"id": "org-ghilotti-bros-inc", "display_label": "Ghilotti Bros., Inc."},
    {"id": "org-ghilotti-bros-contractors", "display_label": "Ghilotti Bros Contractors"},
    {"id": "org-miller-pacific-engineering-group", "display_label": "Miller Pacific Engineering Group"},
    {"id": "org-cumming-management-group", "display_label": "Cumming Management Group"},
    {"id": "org-cummings-management-group-inc", "display_label": "Cummings Management Group, Inc"},
]
# (existing_id, true_sos_id, expected_top_rank?) — top-rank only for exact/high-difflib.
EXPECT = [
    ("org-ghilotti-construction", "1819837", False),
    ("org-ghilotti-construction-company", "1819837", True),
    ("org-ghilotti-bros-inc", "0257045", True),
    ("org-ghilotti-bros-contractors", "0257045", False),
    ("org-miller-pacific-engineering-group", "1628638", True),
    ("org-cumming-management-group", "2976512", True),
    ("org-cummings-management-group-inc", "2976512", True),
]


@pytest.fixture(scope="module")
def real_block():
    with open(REAL_FILINGS, encoding="utf-8") as fh:  # streamed line by line
        return block_casos_against_existing(fh, FORPROFIT)


@real_present
class TestRealCaSosE2E:
    def test_real_for_profit_cases_surface_queued_with_city(self, real_block):
        for existing_id, true_sos, want_top in EXPECT:
            cands = [c for c in real_block["candidates"] if c["candidate_ref"] == existing_id]
            assert cands, f"{existing_id} surfaced no candidates"
            by_num = {c["sos_id"]: c for c in cands}
            assert true_sos in by_num, f"{existing_id} missing true entity {true_sos}"
            assert by_num[true_sos].get("registry_principal_city"), f"{true_sos} missing city corroboration"
            if want_top:
                top = sorted(cands, key=lambda c: (-c["signal_strength"]))[0]
                # the true entity is among the very top by signal (exact-first ranking)
                assert true_sos in {c["sos_id"] for c in cands if c["signal_strength"] >= top["signal_strength"] - 1e-9} \
                    or by_num[true_sos]["signal_strength"] >= 0.9

    def test_miller_novato_not_the_stockton_false_friend(self, real_block):
        mp = {c["sos_id"]: c for c in real_block["candidates"]
              if c["candidate_ref"] == "org-miller-pacific-engineering-group"}
        assert mp["1628638"]["registry_principal_city"] == "Novato"
        # if the Stockton false friend appears at all, it is a distinct, lower-ranked candidate
        if "1539723" in mp:
            assert mp["1539723"]["signal_strength"] <= mp["1628638"]["signal_strength"]

    def test_all_queued_never_auto_merged(self, real_block):
        assert real_block["candidates"]
        assert all(c["status"] == "queued" for c in real_block["candidates"])

    def test_real_run_is_redaction_clean(self, real_block):
        assert scan_for_forbidden(real_block["candidates"]) == []
        report = build_casos_coverage_report(real_block, FORPROFIT)
        assert scan_for_forbidden(report) == []
        assert report["redaction"]["person_fields_published"] == 0

    def test_streamed_the_whole_file(self, real_block):
        # the streaming pass saw the full registry (sanity: millions of rows)
        assert real_block["stats"]["filings_rows_scanned"] > 9_000_000


# --------------------------------------------------------------------------
# Approve → surface on the real Ghilotti label (constructed; no real file needed)
# --------------------------------------------------------------------------


def test_operator_approval_surfaces_exactly_one_real_sos_id(tmp_path):
    assert KEY_NORMALIZERS["sos_id"] is not None
    key_node = {
        "id": "org-casos-1819837", "display_label": "Ghilotti Construction Company, Inc.",
        "sos_id": "1819837", "entity_status": "Active",
        "entity_type": "Stock Corporation - CA - General", "formation_date": "04/23/1992",
    }
    existing = {"id": "org-ghilotti-construction-company", "display_label": "Ghilotti Construction Company"}
    a = make_assertion(
        subject_ref=key_node["id"], target_ref=existing["id"], status="approved",
        basis="operator_approved_sos_id", subject=key_node, target=existing,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-21", policy_version="v1",
        evidence_refs=["record-casos-1819837"],
    )
    record = {
        "id": existing["id"], "display_label": existing["display_label"],
        "own_ein": None, "own_uei": None, "own_sos_id": None, "own_source": None,
        "own_irs_subsection_class": None, "degree": 6,
        "key_links": [{
            "linked_node_id": key_node["id"], "edge_source_id": key_node["id"],
            "edge_target_id": existing["id"], "assertion_id": a["id"],
            "ein": None, "uei": None, "sos_id": "1819837", "irs_subsection_class": None,
            "entity_status": "Active", "entity_type": "Stock Corporation - CA - General",
            "formation_date": "04/23/1992",
        }],
    }

    class _FakeSession:
        def run(self, _q):
            return iter([record, {"id": "org-other", "display_label": "Other", "key_links": []}])

    import json
    out = tmp_path / "enriched.json"
    write_enriched_orgs(out, _FakeSession(), [a])
    emitted = json.loads(out.read_text())
    with_sos = [r for r in emitted if r.get("sos_id")]
    assert len(with_sos) == 1
    assert with_sos[0]["sos_id"] == "1819837"
    assert with_sos[0]["entity_status"] == "Active"
    assert scan_for_forbidden(emitted) == []
