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
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from org_resolution import _normalize_name  # consumed, never edited
from enrich_org_keys import (  # consumed, never edited
    resolve_registry_refs,
    assertion_for_approved_candidate,
    parse_bmf_csv,
)

POLICY_VERSION = "county-vendor-ein-v1"
_EIN_ANCHOR_PREFIX = "org-bmf-ein-"

# The resolver's name-similarity threshold (org_resolution._SIMILARITY_THRESHOLD).
_SIMILARITY_THRESHOLD = 0.85
# Provable lower bound on min/max length for difflib ratio ≥ 0.85.
_LENGTH_BAND = _SIMILARITY_THRESHOLD / (2 - _SIMILARITY_THRESHOLD)  # ≈ 0.7391


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
    hits ∪ length-banded refs that survive the `difflib.quick_ratio` prefilter.

    Both prunes are PROVABLY lossless for the resolver's `ratio ≥ 0.85` branch:
    the length band (`min/max ≥ 0.739`) and `quick_ratio()` are UPPER BOUNDS on
    `ratio()`, so anything dropped could never have matched. `quick_ratio` (a
    char-multiset bound, O(len)) prunes the bulk of length-banded non-matches
    cheaply before the resolver's O(len²) `ratio()` — chosen over a char-trigram
    heuristic precisely because it cannot drop a true match (e.g. `aaa`/`aaba`,
    `quick_ratio` 0.857). Deduped by id; order-stable."""
    label = vendor["display_label"]
    vn = label.casefold()
    lv = len(vn)
    seen: dict[str, dict[str, Any]] = {}
    # equality branch — UNBANDED (length-independent)
    for r in index.exact.get(_normalize_name(label), []):
        seen[r["id"]] = r
    # difflib branch — provable length band + lossless quick_ratio upper-bound prune
    matcher = SequenceMatcher()
    matcher.set_seq2(vn)
    for r, rl in zip(index.refs, index.lengths):
        if r["id"] in seen or not length_band_ok(lv, rl):
            continue
        matcher.set_seq1(r["display_label"].casefold())
        if matcher.quick_ratio() >= _SIMILARITY_THRESHOLD:
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


def coverage_report(
    vendor_orgs: list[dict[str, Any]], bmf_refs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Honest coverage + ambiguity + pool-shape. Reports vendors with ≥1 / 0 /
    multi EIN candidate, EINs proposed for MORE THAN ONE vendor
    (`ein_reused_across_vendors`, with ids), zero-`_normalize_name` vendors, and
    the candidate-pool shape (max / p95 / total comparisons / resolve calls) so a
    data refresh that balloons a token bucket fails loudly."""
    index = build_bmf_index(bmf_refs)
    pool_sizes: list[int] = []
    by_vendor_eins: dict[str, set[str]] = defaultdict(set)
    ein_to_vendors: dict[str, set[str]] = defaultdict(set)
    zero_token = 0
    for vendor in vendor_orgs:
        if not _normalize_name(vendor["display_label"]):
            zero_token += 1
        pool = candidate_bmf_for(vendor, index)
        pool_sizes.append(len(pool))
        if not pool:
            continue
        for cand in resolve_registry_refs(pool, [vendor])["review_candidates"]:
            anchor, vid = cand["subject_ref"], cand["candidate_ref"]
            by_vendor_eins[vid].add(anchor)
            ein_to_vendors[anchor].add(vid)
    sizes = sorted(pool_sizes)

    def _pct(p: float) -> int:
        return sizes[min(len(sizes) - 1, int(p * len(sizes)))] if sizes else 0

    reused = {a: sorted(vs) for a, vs in ein_to_vendors.items() if len(vs) > 1}
    return {
        "vendor_orgs_total": len(vendor_orgs),
        "with_ein_candidate": len(by_vendor_eins),
        "zero_candidate": len(vendor_orgs) - len(by_vendor_eins),
        "multi_candidate_vendors": sum(1 for eins in by_vendor_eins.values() if len(eins) > 1),
        "ein_reused_across_vendors": reused,
        "ein_reused_count": len(reused),
        "zero_token_vendors": zero_token,
        "max_pool": max(pool_sizes) if pool_sizes else 0,
        "p95_pool": _pct(0.95),
        "total_comparisons": sum(pool_sizes),
        "resolve_calls": sum(1 for s in pool_sizes if s),
    }


def build_ein_attach(
    candidate: dict[str, Any],
    vendor_ref: dict[str, Any],
    *,
    reviewer: str,
    decided_at: str,
    policy_version: str = POLICY_VERSION,
    policy_hash: str | None = None,
    eligibility_snapshot_hash: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """For an operator-APPROVED EIN candidate, build (assertion, SAME_AS edge) —
    mirrors FPPC `build_committee_attach`. subject = the `org-bmf-ein-<ein>` key
    anchor (carrying the ein), target = the vendor org; basis
    `operator_approved_ein`; SAME_AS anchor → vendor citing the assertion id.
    `assertion_for_approved_candidate` alone writes only the ledger row — the
    SAME_AS is what `export_existing_orgs --enriched` reads to surface the ein."""
    anchor_id = candidate["subject_ref"]
    ein = candidate.get("ein") or anchor_id[len(_EIN_ANCHOR_PREFIX):]
    subject = {
        "id": anchor_id,
        "display_label": vendor_ref.get("display_label", anchor_id),
        "ein": ein,
        "source": "irs_bmf",
    }
    target = vendor_ref if vendor_ref.get("id") else {"id": candidate["candidate_ref"]}
    assertion = assertion_for_approved_candidate(
        candidate, subject=subject, target=target,
        basis="operator_approved_ein",
        reviewer=reviewer, decided_at=decided_at, policy_version=policy_version,
        policy_hash=policy_hash, eligibility_snapshot_hash=eligibility_snapshot_hash,
    )
    same_as = {
        "source_id": anchor_id,
        "target_id": candidate["candidate_ref"],
        "relationship_type": "SAME_AS",
        "properties": {"basis": "operator_approved_ein", "assertion_id": assertion["id"]},
    }
    return assertion, same_as


def _load_vendor_orgs(input_csv, approved_path) -> list[dict[str, Any]]:
    """The Phase-A vendor org set: parse_contract_rows → build_recipient_groups →
    exclude the 43 approved group_ids → build_vendor_org_nodes (all consumed)."""
    import json
    from ingest_marin_county_contracts import build_recipient_groups, parse_contract_rows
    from build_county_vendor_orgs import build_vendor_org_nodes
    rows = parse_contract_rows(input_csv)
    groups = build_recipient_groups(rows)
    approved = {
        json.loads(line)["subject_ref"]
        for line in Path(approved_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return [{"id": n["id"], "display_label": n["display_label"]}
            for n in build_vendor_org_nodes(groups, approved_group_ids=approved)]


def main(argv: list[str] | None = None) -> int:
    """Pure build: write the QUEUED vendor→EIN candidates + the coverage report for
    operator review. NO attach/dedup/load (operator steps).

    Operator approve→attach runbook: for each APPROVED candidate, call
    `build_ein_attach(candidate, vendor_ref, reviewer=..., decided_at=...)` →
    append the assertion to the ledger + draw the SAME_AS edge; re-export enriched
    (`export_existing_orgs --enriched`) so the vendor surfaces its `ein`; then run
    the shipped dedup so vendor↔990/existing collapse by hard key."""
    import argparse
    import json

    p = argparse.ArgumentParser(description="County Attribution Phase B — propose vendor EINs (queued)")
    p.add_argument("--vendors-inline", help="JSON list of {id, display_label} (testing/small)")
    p.add_argument("--input", type=Path, help="delegated-contracts.csv")
    p.add_argument("--approved", type=Path, help="approved-resolutions.jsonl (the 43)")
    p.add_argument("--bmf", type=Path, required=True, help="IRS EO-BMF csv (eo_ca.csv)")
    p.add_argument("--out-dir", type=Path, required=True, help="review output dir")
    args = p.parse_args(argv)

    if args.vendors_inline:
        vendors = json.loads(args.vendors_inline)
    else:
        if not (args.input and args.approved):
            p.error("provide --vendors-inline OR both --input and --approved")
        vendors = _load_vendor_orgs(args.input, args.approved)

    bmf_refs = parse_bmf_csv(args.bmf)["refs"]
    result = resolve_vendor_eins(vendors, bmf_refs)
    report = coverage_report(vendors, bmf_refs)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vendor-ein-candidates.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in result["candidates"]),
        encoding="utf-8",
    )
    (out_dir / "coverage.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    printable = {k: v for k, v in report.items() if k != "ein_reused_across_vendors"}
    print(json.dumps(printable, indent=2))
    print("QUEUED only — NO EIN attached. Operator: review the candidates, then build_ein_attach "
          "each APPROVED one (assertion + SAME_AS) → ledger → re-export enriched → dedup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
