"""enrich_county_vendor_eins.py — Open Marin · County Attribution Phase B (EIN).

Phase A created name-only County vendor `Organization` nodes (`org-marincontract-
recipient-*`). Phase B proposes an IRS EIN for each by name-resolving against the
CA-wide IRS EO-BMF, QUEUED for operator review (a name match NEVER auto-attaches a
key). Operator approval attaches the EIN via Identity Control A; the deterministic
dedup tier can then collapse vendor↔990/existing dups by hard key and surface
dual-role nonprofits.

LOSSLESS blocker (the resolver matches `_normalize_name` equality OR
`difflib.ratio ≥ 0.85` over RAW casefolded `display_label`). The candidate pool
per vendor is the UNION of:
  - UNBANDED exact-`_normalize_name` index hits — length-INDEPENDENT (the equality
    branch can pass below the length band, e.g. `RISE SCHOLARS INC` ↔
    `Rise Scholars Incorporated`, raw length ratio 0.654);
  - length-banded refs — PROVABLE bound `ratio ≤ 2·min/(la+lb)`, so
    `ratio ≥ 0.85 ⇒ min/max ≥ 0.85/1.15 ≈ 0.739` on casefold raw lengths.
Char-trigram pruning of the length-banded branch is an OPTIONAL perf optimization
(short-name bypass), GUARDED by the candidate-SET-parity test — it is NOT part of
the lossless guarantee. `org_resolution` / the shipped lanes are CONSUMED, never
edited.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from org_resolution import _normalize_name  # consumed, never edited
from enrich_org_keys import resolve_registry_refs  # consumed, never edited

# Provable lower bound on min/max length for difflib ratio ≥ 0.85.
_LENGTH_BAND = 0.85 / 1.15  # ≈ 0.7391


def length_band_ok(la: int, lb: int) -> bool:
    """True iff two casefold-name lengths CAN yield `difflib.ratio ≥ 0.85`
    (`min/max ≥ 0.739`). Lossless for the difflib branch — names outside the band
    can never match. Two empty names are equal."""
    if la == 0 or lb == 0:
        return la == lb
    return min(la, lb) / max(la, lb) >= _LENGTH_BAND


class BmfIndex:
    """Blocking index over BMF registry refs: an UNBANDED exact-`_normalize_name`
    map (the equality branch) + the refs with their casefold lengths (the
    length-banded difflib branch)."""

    def __init__(self, refs: list[dict[str, Any]]):
        self.refs = refs
        self.exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.lengths: list[int] = []
        for r in refs:
            self.exact[_normalize_name(r["display_label"])].append(r)
            self.lengths.append(len(r["display_label"].casefold()))


def build_bmf_index(refs: list[dict[str, Any]]) -> BmfIndex:
    return BmfIndex(refs)


def candidate_bmf_for(vendor: dict[str, Any], index: BmfIndex) -> list[dict[str, Any]]:
    """The LOSSLESS candidate pool for a vendor = UNBANDED exact-`_normalize_name`
    hits ∪ length-banded refs (the difflib branch). Deduped by id; order-stable."""
    label = vendor["display_label"]
    lv = len(label.casefold())
    seen: dict[str, dict[str, Any]] = {}
    # equality branch — UNBANDED (length-independent)
    for r in index.exact.get(_normalize_name(label), []):
        seen[r["id"]] = r
    # difflib branch — provable length band
    for r, rl in zip(index.refs, index.lengths):
        if length_band_ok(lv, rl):
            seen[r["id"]] = r
    return list(seen.values())


def resolve_vendor_eins(
    vendor_orgs: list[dict[str, Any]], bmf_refs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Per vendor, resolve its LOSSLESS BMF candidate pool through the shipped
    `resolve_registry_refs` → QUEUED name candidates. Vendor orgs are key-less, so
    the deterministic-merge branch never fires (same_as_edges / assertions stay
    empty — NO auto-attach; the cardinal rule). RAW resolver direction is kept
    (subject_ref = `org-bmf-ein-*`, candidate_ref = vendor); `vendor_ref` /
    `ein_anchor_ref` are added for vendor-first operator display."""
    index = build_bmf_index(bmf_refs)
    candidates: list[dict[str, Any]] = []
    same_as_edges: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    for vendor in vendor_orgs:
        pool = candidate_bmf_for(vendor, index)
        if not pool:
            continue
        res = resolve_registry_refs(pool, [vendor])
        same_as_edges.extend(res["same_as_edges"])
        assertions.extend(res["assertions"])
        for cand in res["review_candidates"]:
            enriched = dict(cand)
            enriched["vendor_ref"] = cand["candidate_ref"]
            enriched["ein_anchor_ref"] = cand["subject_ref"]
            candidates.append(enriched)
    return {
        "candidates": candidates,
        "same_as_edges": same_as_edges,
        "assertions": assertions,
    }
