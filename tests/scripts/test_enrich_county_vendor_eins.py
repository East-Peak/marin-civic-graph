"""Tests for scripts/enrich_county_vendor_eins.py — County Attribution Phase B.

Unit 1: the LOSSLESS blocker primitives. The resolver matches on
`_normalize_name` equality OR `difflib.ratio ≥ 0.85` over RAW casefolded names.
The lossless candidate pool per vendor = UNBANDED exact-`_normalize_name` hits
∪ length-banded (`min/max ≥ 0.739` on casefold raw lengths) refs. The exact
branch MUST be unbanded — `RISE SCHOLARS INC` ↔ `Rise Scholars Incorporated`
is normalized-equal but raw length ratio 0.654 (out of band).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from enrich_county_vendor_eins import (  # noqa: E402
    build_bmf_index,
    candidate_bmf_for,
    length_band_ok,
)


def _ref(rid, label, ein):
    return {"id": rid, "display_label": label, "ein": ein}


def test_length_band_ok_provable_bound():
    assert length_band_ok(10, 10) is True
    assert length_band_ok(10, 8) is True            # 0.80 ≥ 0.739
    assert length_band_ok(26, 20) is True           # 0.769
    assert length_band_ok(26, 17) is False          # 0.654 — out of band
    assert length_band_ok(10, 7) is False           # 0.70


def test_build_bmf_index_has_unbanded_exact_map():
    refs = [_ref("org-bmf-ein-1", "Rise Scholars Incorporated", "844738834"),
            _ref("org-bmf-ein-2", "Vivalon", "111111111")]
    idx = build_bmf_index(refs)
    # exact map keyed by _normalize_name (suffix-stripped) → the ref
    hits = idx.exact.get("rise scholars")
    assert hits and hits[0]["ein"] == "844738834"


def test_candidate_pool_includes_out_of_band_exact_match():
    # the RISE SCHOLARS case: normalized-equal but raw length ratio 0.654 (out of band)
    refs = [_ref("org-bmf-ein-1", "Rise Scholars Incorporated", "844738834")]
    idx = build_bmf_index(refs)
    vendor = {"id": "org-marincontract-recipient-rise-scholars", "display_label": "RISE SCHOLARS INC"}
    pool_ids = {r["id"] for r in candidate_bmf_for(vendor, idx)}
    assert "org-bmf-ein-1" in pool_ids  # via the UNBANDED exact branch, despite being out of band


def test_candidate_pool_length_bands_the_difflib_branch():
    refs = [
        _ref("org-bmf-ein-near", "Marin Food Banks", "1"),  # in-band, NOT normalized-equal
        _ref("org-bmf-ein-far", "A" * 80, "2"),             # far out of length band
    ]
    idx = build_bmf_index(refs)
    vendor = {"id": "org-v", "display_label": "Marin Food Bank"}  # normalizes ≠ "marin food banks"
    pool_ids = {r["id"] for r in candidate_bmf_for(vendor, idx)}
    assert "org-bmf-ein-near" in pool_ids     # in the length band (non-exact) → candidate
    assert "org-bmf-ein-far" not in pool_ids  # out of band, not exact → pruned losslessly


# --------------------------------------------------------------------------
# Unit 2 — resolve_vendor_eins: per-vendor blocked resolve → QUEUED candidates,
# raw resolver direction (subject=ein-anchor, candidate=vendor), no auto-attach.
# --------------------------------------------------------------------------
from enrich_county_vendor_eins import resolve_vendor_eins  # noqa: E402


def _vendor(vid, label):
    return {"id": vid, "display_label": label}


def test_resolve_vendor_eins_queued_name_candidates_raw_direction():
    vendors = [_vendor("org-marincontract-recipient-vivalon", "Vivalon")]
    bmf = [_ref("org-bmf-ein-111111111", "Vivalon", "111111111"),
           _ref("org-bmf-ein-999999999", "Unrelated Co", "999999999")]
    out = resolve_vendor_eins(vendors, bmf)
    cands = out["candidates"]
    assert cands, "expected a name candidate for the exact-name vendor"
    c = next(c for c in cands if c["subject_ref"] == "org-bmf-ein-111111111")
    assert c["status"] == "queued"
    assert c["subject_ref"].startswith("org-bmf-ein-")               # raw: registry is subject
    assert c["candidate_ref"] == "org-marincontract-recipient-vivalon"  # raw: vendor is candidate
    assert c["ein_anchor_ref"] == "org-bmf-ein-111111111"            # presentation
    assert c["vendor_ref"] == "org-marincontract-recipient-vivalon"  # presentation


def test_keyless_vendor_never_auto_attaches():
    # vendor orgs carry no ein → resolve_registry_refs' deterministic-merge branch
    # never fires → NO same_as edges, NO assertions (queued candidates only).
    vendors = [_vendor("org-v", "Vivalon")]
    bmf = [_ref("org-bmf-ein-111111111", "Vivalon", "111111111")]
    out = resolve_vendor_eins(vendors, bmf)
    assert out["same_as_edges"] == []
    assert out["assertions"] == []
    assert all(c["status"] == "queued" for c in out["candidates"])


# --------------------------------------------------------------------------
# Unit 3 — coverage report: ein_reused_across_vendors, multi-candidate,
# zero-token vendors, pool-shape stats.
# --------------------------------------------------------------------------
from enrich_county_vendor_eins import coverage_report  # noqa: E402


def test_coverage_report_reuse_multi_and_zero_token():
    vendors = [
        _vendor("org-marincontract-recipient-vivalon", "Vivalon"),
        _vendor("org-marincontract-recipient-vivalon-x", "Vivalon"),   # same name → reused EIN
        _vendor("org-marincontract-recipient-helping", "Helping Hands"),  # two EINs → multi
        _vendor("org-marincontract-recipient-blank", "###"),            # normalizes to "" → zero-token
    ]
    bmf = [
        _ref("org-bmf-ein-111", "Vivalon", "111"),
        _ref("org-bmf-ein-222", "Helping Hands", "222"),
        _ref("org-bmf-ein-333", "Helping Hands Inc", "333"),  # also exact-normalizes to "helping hands"
    ]
    rep = coverage_report(vendors, bmf)
    assert rep["vendor_orgs_total"] == 4
    assert rep["with_ein_candidate"] == 3            # the two Vivalons + Helping Hands
    assert rep["zero_candidate"] == 1                # the ### vendor
    assert rep["zero_token_vendors"] == 1
    assert rep["multi_candidate_vendors"] == 1       # Helping Hands → ein 222 + 333
    # EIN 111 proposed for BOTH Vivalon vendors → reused across vendors
    assert "org-bmf-ein-111" in rep["ein_reused_across_vendors"]
    assert len(rep["ein_reused_across_vendors"]["org-bmf-ein-111"]) == 2
    # pool-shape stats present
    assert rep["max_pool"] >= 1 and rep["total_comparisons"] >= 1 and "p95_pool" in rep


# --------------------------------------------------------------------------
# Unit 4 — candidate-SET-parity (THE losslessness guarantor): the blocked match
# set == the full unblocked resolver match set. 3 adversarial pins REQUIRED-caught.
# --------------------------------------------------------------------------
from enrich_org_keys import resolve_registry_refs as _rrr  # noqa: E402


def _ground_truth_pairs(vendors, bmf):
    # full cross-product reference: every BMF ref vs each vendor (no blocking)
    pairs = set()
    for v in vendors:
        for c in _rrr(bmf, [v])["review_candidates"]:
            pairs.add((c["subject_ref"], c["candidate_ref"]))
    return pairs


def _blocked_pairs(vendors, bmf):
    return {(c["subject_ref"], c["candidate_ref"])
            for c in resolve_vendor_eins(vendors, bmf)["candidates"]}


def test_blocker_set_parity_with_adversarial_pins():
    vendors = [
        _vendor("org-marincontract-recipient-rise-scholars", "RISE SCHOLARS INC"),  # exact, out-of-band
        _vendor("org-marincontract-recipient-aaa", "aaa"),                          # in-band, 0-trigram
        _vendor("org-marincontract-recipient-marinlink", "Marinlink"),              # difflib 0.947
        _vendor("org-marincontract-recipient-zzz", "Zzz Wholly Unrelated Vendor"),  # no match
    ]
    bmf = [
        _ref("org-bmf-ein-1", "Rise Scholars Incorporated", "1"),
        _ref("org-bmf-ein-2", "aaba", "2"),
        _ref("org-bmf-ein-3", "Marin Link", "3"),
        _ref("org-bmf-ein-4", "Totally Different Name", "4"),
    ]
    blocked = _blocked_pairs(vendors, bmf)
    ground = _ground_truth_pairs(vendors, bmf)
    assert blocked == ground, f"blocker is LOSSY: missed {ground - blocked}, extra {blocked - ground}"
    # the three adversarial pins are all caught
    assert ("org-bmf-ein-1", "org-marincontract-recipient-rise-scholars") in blocked
    assert ("org-bmf-ein-2", "org-marincontract-recipient-aaa") in blocked
    assert ("org-bmf-ein-3", "org-marincontract-recipient-marinlink") in blocked


# --------------------------------------------------------------------------
# Unit 5 — build_ein_attach (assertion + SAME_AS) → surfaces ein via enriched
# export → feeds the deterministic dedup tier (the whole payoff).
# --------------------------------------------------------------------------
from enrich_county_vendor_eins import build_ein_attach  # noqa: E402
from export_existing_orgs import org_ref_from_enriched_record  # noqa: E402
from dedup_org_candidates import deterministic_dedup_assertions  # noqa: E402

_CAND = {"subject_ref": "org-bmf-ein-844738834",
         "candidate_ref": "org-marincontract-recipient-rise-scholars",
         "evidence_record_ids": []}
_VENDOR = {"id": "org-marincontract-recipient-rise-scholars", "display_label": "RISE SCHOLARS INC"}


def test_build_ein_attach_yields_assertion_and_same_as():
    assertion, same_as = build_ein_attach(_CAND, _VENDOR, reviewer="stuart@eastpeak.cc",
                                          decided_at="2026-06-23", policy_version="v1")
    assert assertion["status"] == "approved" and assertion["basis"] == "operator_approved_ein"
    assert assertion["subject_ref"] == "org-bmf-ein-844738834"          # anchor is subject
    assert assertion["target_ref"] == "org-marincontract-recipient-rise-scholars"
    assert same_as["source_id"] == "org-bmf-ein-844738834"
    assert same_as["target_id"] == "org-marincontract-recipient-rise-scholars"
    assert same_as["relationship_type"] == "SAME_AS"
    assert same_as["properties"]["assertion_id"] == assertion["id"]


def test_attach_surfaces_ein_via_enriched_export():
    assertion, same_as = build_ein_attach(_CAND, _VENDOR, reviewer="stuart@eastpeak.cc",
                                          decided_at="2026-06-23", policy_version="v1")
    link = {"linked_node_id": same_as["source_id"], "edge_source_id": same_as["source_id"],
            "edge_target_id": same_as["target_id"], "assertion_id": assertion["id"],
            "ein": "844738834", "uei": None, "sos_id": None, "committee_id": None,
            "irs_subsection_class": None, "entity_status": None, "entity_type": None,
            "formation_date": None}
    record = {"id": _VENDOR["id"], "display_label": _VENDOR["display_label"],
              "own_ein": None, "own_uei": None, "own_sos_id": None, "own_committee_id": None,
              "own_source": None, "own_irs_subsection_class": None, "degree": 1, "key_links": [link]}
    ref = org_ref_from_enriched_record(record, {assertion["id"]: assertion})
    assert ref["ein"] == "844738834"   # the SAME_AS surfaces the ein on the vendor (Codex r1 #3)


def test_approved_ein_feeds_deterministic_dedup():
    # the payoff: a keyed vendor dedup-merges with its 990/existing identity by EIN
    refs = [
        {"id": "org-marincontract-recipient-rise-scholars", "display_label": "Rise Scholars", "ein": "844738834"},
        {"id": "org-990-rise-scholars", "display_label": "Rise Scholars Inc", "ein": "844738834"},
    ]
    asserts = deterministic_dedup_assertions(refs, reviewer="dedup", policy_version="v1")
    assert any(a["basis"] == "org_dedup_key_exact" for a in asserts)


# --------------------------------------------------------------------------
# Unit 6 — CLI (--build writes queued candidates + coverage) + env-gated real e2e
# --------------------------------------------------------------------------
import os  # noqa: E402
import json as _json  # noqa: E402
import pytest  # noqa: E402

from enrich_county_vendor_eins import main  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_CSV = _ROOT / "data" / "raw" / "marin-county-delegated-contracts" / "2026-06-10" / "delegated-contracts.csv"
_APPROVED = _ROOT / "data" / "review" / "county" / "approved-resolutions.jsonl"
_BMF = _ROOT / "data" / "raw" / "irs-bmf" / "eo_ca.csv"
_RUN_E2E = os.environ.get("RUN_PHASE_B_E2E")


def test_cli_build_writes_candidates_and_coverage(tmp_path):
    # small fabricated inputs via direct call paths would need the ingestor; instead
    # drive main with a tiny BMF + the real (fast) plumbing on a 1-vendor slice.
    bmf_csv = tmp_path / "bmf.csv"
    bmf_csv.write_text("EIN,NAME,STATE,CITY,SUBSECTION\n111111111,VIVALON,CA,SAN RAFAEL,03\n", encoding="utf-8")
    out = tmp_path / "out"
    rc = main(["--vendors-inline", _json.dumps([{"id": "org-marincontract-recipient-vivalon",
                                                 "display_label": "Vivalon"}]),
               "--bmf", str(bmf_csv), "--out-dir", str(out)])
    assert rc == 0
    cands = [_json.loads(l) for l in (out / "vendor-ein-candidates.jsonl").read_text().splitlines() if l.strip()]
    assert any(c["ein_anchor_ref"].startswith("org-bmf-ein-") for c in cands)
    report = _json.loads((out / "coverage.json").read_text())
    assert report["vendor_orgs_total"] == 1 and report["with_ein_candidate"] == 1


@pytest.mark.skipif(not _RUN_E2E, reason="slow real e2e — set RUN_PHASE_B_E2E=1")
def test_e2e_real_bmf_ein_coverage_and_pool_shape():
    import time
    from ingest_marin_county_contracts import parse_contract_rows, build_recipient_groups
    from build_county_vendor_orgs import build_vendor_org_nodes
    from enrich_org_keys import parse_bmf_csv
    from enrich_county_vendor_eins import coverage_report
    rows = parse_contract_rows(_CSV)
    groups = build_recipient_groups(rows)
    approved = {_json.loads(l)["subject_ref"] for l in _APPROVED.read_text().splitlines() if l.strip()}
    vorgs = [{"id": n["id"], "display_label": n["display_label"]}
             for n in build_vendor_org_nodes(groups, approved_group_ids=approved)]
    bmf = parse_bmf_csv(_BMF)["refs"]
    t = time.time()
    rep = coverage_report(vorgs, bmf)
    elapsed = time.time() - t
    assert rep["vendor_orgs_total"] == 2087
    assert rep["with_ein_candidate"] == 268        # == the naive full-cross-product ground truth
    assert rep["multi_candidate_vendors"] == 62
    assert rep["ein_reused_count"] == 30
    assert rep["max_pool"] < 5000                  # pool-shape budget (actual 938) — no balloon
    assert elapsed < 900                           # perf budget (actual ~318s)


@pytest.mark.skipif(not _RUN_E2E, reason="slow real e2e — set RUN_PHASE_B_E2E=1")
def test_e2e_real_data_set_parity_sample():
    # rigorous real-data check: the blocked match set == the FULL unblocked
    # resolver match set on a sample of real vendors (quick_ratio is a proven
    # upper bound, so this must hold — this catches any implementation drift).
    from ingest_marin_county_contracts import parse_contract_rows, build_recipient_groups
    from build_county_vendor_orgs import build_vendor_org_nodes
    from enrich_org_keys import parse_bmf_csv
    rows = parse_contract_rows(_CSV)
    groups = build_recipient_groups(rows)
    approved = {_json.loads(l)["subject_ref"] for l in _APPROVED.read_text().splitlines() if l.strip()}
    vorgs = [{"id": n["id"], "display_label": n["display_label"]}
             for n in build_vendor_org_nodes(groups, approved_group_ids=approved)][:25]
    bmf = parse_bmf_csv(_BMF)["refs"]
    blocked = {(c["subject_ref"], c["candidate_ref"])
               for c in resolve_vendor_eins(vorgs, bmf)["candidates"]}
    ground = set()
    for v in vorgs:
        for c in _rrr(bmf, [v])["review_candidates"]:
            ground.add((c["subject_ref"], c["candidate_ref"]))
    assert blocked == ground, f"real-data drift: missed {ground - blocked}, extra {blocked - ground}"
