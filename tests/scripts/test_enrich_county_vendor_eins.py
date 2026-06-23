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
