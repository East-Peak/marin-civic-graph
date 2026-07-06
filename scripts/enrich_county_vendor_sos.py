"""enrich_county_vendor_sos.py — Open Marin · County Attribution Phase C (CA-SOS sos_id).

Phase A created name-only County vendor `Organization` nodes (`org-marincontract-
recipient-*`); Phase B keyed the nonprofit bucket to EINs. Phase C name-resolves
ALL 2,087 vendor orgs against the staged CA Secretary-of-State Filings export
(9.44M rows) to propose `sos_id` keys, QUEUED for operator review (a name match
NEVER auto-attaches a key). CA-SOS carries natural-person home addresses — the
shipped Lane-2 redaction gate (`publishable_casos_fields` + `scan_for_forbidden` +
`individual_agent_flags`) is the load-bearing invariant.

Right-sized blocker (Stuart: "the elegant way"): the recall net is significant-token
overlap OR a SUFFIX-AWARE compact key (closes the `Marinlink`/`Marin Link` +
fused-suffix fuzzy class with no char-trigram index); a PROVABLE lossless prefilter
(`length_band_ok` + `quick_ratio≥0.85` + exact-normalize) then gates the expensive
resolver; the output is the RESOLVER tier only (exact / difflib≥0.85),
confidence-tiered. All shipped modules are CONSUMED, never edited.
"""
from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from org_resolution import (  # consumed, never edited
    _NAME_SUFFIXES,
    _normalize_name,
    propose_org_resolutions,
)
from enrich_casos_keys import (  # consumed, never edited
    parse_casos_agents,
    parse_casos_filings,
    publishable_casos_fields,
    scan_for_forbidden,
    significant_tokens,
)
from enrich_county_vendor_eins import length_band_ok  # consumed (Phase-B lossless bound)
from identity_attach import build_attach as build_identity_attach
from identity_key_registry import entry as identity_key_entry

POLICY_VERSION = "county-vendor-sos-v1"
_SIMILARITY_THRESHOLD = 0.85

# Strip the EXACT suffix set `_normalize_name` strips, longest-first (so
# `incorporated` is peeled before `inc`), repeated (so a fused `...llcinc` → '').
_SUFFIXES_LONGEST_FIRST = tuple(sorted(_NAME_SUFFIXES, key=len, reverse=True))


def _strip_fused_suffix(s: str) -> str:
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES_LONGEST_FIRST:
            if len(s) > len(suf) and s.endswith(suf):
                s = s[: -len(suf)]
                changed = True
                break
    return s


def compact_key(name: str) -> str:
    """`_normalize_name` (casefold, punct→space, strip tokenized suffixes) → drop
    spaces → strip FUSED trailing suffixes. Collapses spacing + fused-suffix
    variants (`Foo LLC`/`FooLLC`/`FooLLCInc`→`foo`) so the no-shared-token fuzzy
    class blocks. Uses ONLY `_NAME_SUFFIXES` — `Cisco` (no such suffix) is safe."""
    return _strip_fused_suffix(_normalize_name(name).replace(" ", ""))


def blocks_to(sos_ref: dict[str, Any], vendor_ref: dict[str, Any]) -> bool:
    """The recall net: a SOS row blocks to a vendor iff they share ≥1 significant
    token OR have the same compact key. Over-inclusive by design — the lossless
    prefilter + resolver supply precision; this only bounds what they examine."""
    sos_name, vendor_name = sos_ref["display_label"], vendor_ref["display_label"]
    if significant_tokens(sos_name) & significant_tokens(vendor_name):
        return True
    return compact_key(sos_name) == compact_key(vendor_name)


def _prefilter(vendor_cf: str, sos_cf: str, vendor_norm: str, sos_norm: str) -> bool:
    """LOSSLESS gate before the expensive resolver: the equality branch
    (`_normalize_name` match) OR the difflib branch's UPPER BOUNDS — the length
    band + `quick_ratio` (both ≥ `ratio`). Drops only pairs the resolver could
    never accept; cuts the 137.6M blocked pairs to the resolver survivors."""
    if vendor_norm == sos_norm:
        return True
    if not length_band_ok(len(vendor_cf), len(sos_cf)):
        return False
    return SequenceMatcher(None, vendor_cf, sos_cf).quick_ratio() >= _SIMILARITY_THRESHOLD


def _needs_careful_review(vendor_norm: str, sos_norm: str) -> bool:
    """A SHORT normalized key (e.g. `AB Inc`→`ab`) is brittle — flag for the operator."""
    return min(len(vendor_norm.replace(" ", "")), len(sos_norm.replace(" ", ""))) <= 4


def _build_candidate(resolver_cand, sos_ref, vendor_norm, sos_norm):
    """Enrich a resolver-tier candidate to the EXACT Phase-C schema (raw direction +
    presentation + nested redacted sos_ref + flags). `individual_agent` is filled
    later (Unit 4 — the candidate-filtered Agents pass)."""
    return {
        **resolver_cand,  # subject_ref, candidate_ref, signals, confidence, status, evidence_record_ids
        "vendor_ref": resolver_cand["candidate_ref"],
        "sos_anchor_ref": resolver_cand["subject_ref"],
        "sos_ref": publishable_casos_fields(sos_ref),
        "individual_agent": None,
        "needs_careful_review": _needs_careful_review(vendor_norm, sos_norm),
    }


def resolve_pass1(vendor_orgs, filings_lines):
    """Pass 1: stream Filings → block (token/compact index) → LOSSLESS prefilter →
    `propose_org_resolutions(identity_keys=("sos_id",))` on survivors → resolver-tier
    HITS only (never full buckets). Key-less vendors → queued name candidates, no
    same_as. Returns hits + hit_pairs + per-vendor info + stats."""
    tok_index: dict[str, list[str]] = defaultdict(list)
    compact_index: dict[str, list[str]] = defaultdict(list)
    vinfo: dict[str, tuple] = {}
    for v in vendor_orgs:
        label = v["display_label"]
        vinfo[v["id"]] = (v, label.casefold(), _normalize_name(label))
        for t in significant_tokens(label):
            tok_index[t].append(v["id"])
        compact_index[compact_key(label)].append(v["id"])

    hits: list[dict[str, Any]] = []
    hit_pairs: set[tuple[str, str]] = set()
    stats = {"rows_scanned": 0, "block_pairs_evaluated": 0, "resolver_pairs_evaluated": 0}
    for ref, _skip in parse_casos_filings(filings_lines):
        if ref is None:
            continue
        stats["rows_scanned"] += 1
        sname = ref["display_label"]
        scf, snorm = sname.casefold(), _normalize_name(sname)
        blocked: set[str] = set()
        for t in significant_tokens(sname):
            blocked.update(tok_index.get(t, ()))
        blocked.update(compact_index.get(compact_key(sname), ()))
        for vid in blocked:
            stats["block_pairs_evaluated"] += 1
            vendor, vcf, vnorm = vinfo[vid]
            if not _prefilter(vcf, scf, vnorm, snorm):
                continue
            stats["resolver_pairs_evaluated"] += 1
            _edges, cands = propose_org_resolutions([ref], [vendor], identity_keys=("sos_id",))
            for cand in cands:
                hits.append(_build_candidate(cand, ref, vnorm, snorm))
                hit_pairs.add((vid, ref["sos_id"]))
    return {"hits": hits, "hit_pairs": hit_pairs, "vinfo": vinfo, "stats": stats}


def conflict_pass2(filings_lines, hit_pairs, vinfo):
    """Pass 2: re-stream Filings over hit sos_ids; record `(display_label,
    entity_type)` variants ONLY from rows that `blocks_to` the vendor (re-applied —
    `dedupe_casos_refs` only ever sees blocked rows, so a non-blocking same-sos_id
    row must not create a false conflict). A `(vendor, sos_id)` with ≥2 variants is
    a `casos_row_conflict`."""
    hit_vids_by_sos: dict[str, set[str]] = defaultdict(set)
    for vid, sos_id in hit_pairs:
        hit_vids_by_sos[sos_id].add(vid)
    variants: dict[tuple[str, str], set[tuple]] = defaultdict(set)
    for ref, _skip in parse_casos_filings(filings_lines):
        if ref is None or ref["sos_id"] not in hit_vids_by_sos:
            continue
        for vid in hit_vids_by_sos[ref["sos_id"]]:
            if blocks_to(ref, vinfo[vid][0]):
                variants[(vid, ref["sos_id"])].add((ref["display_label"], ref["entity_type"]))
    return {pair for pair, vs in variants.items() if len(vs) > 1}


def attach_individual_agent_flags(candidates, agents_lines) -> int:
    """Fill each candidate's `individual_agent` from a candidate-FILTERED
    `Agents.csv` stream (`parse_casos_agents` reads ONLY entity_num + agent_type —
    never the agent's name/address). Only hit sos_ids are retained (never a
    full-entity flag dict). Returns the count of natural-person-agent candidates."""
    hit_sos = {c["sos_ref"]["sos_id"] for c in candidates}
    flags: dict[str, bool] = {}
    for entity_num, is_individual in parse_casos_agents(agents_lines):
        if entity_num in hit_sos:
            flags[entity_num] = flags.get(entity_num, False) or is_individual
    count = 0
    for c in candidates:
        c["individual_agent"] = flags.get(c["sos_ref"]["sos_id"], False)
        if c["individual_agent"]:
            count += 1
    return count


def resolve_vendor_sos(vendor_orgs, filings_factory, *, agents_factory=None):
    """Two-pass orchestrator (the factory yields a FRESH line iterator per pass).
    Pass 1 → resolver-tier hits; pass 2 → `casos_row_conflict`; candidates =
    hits whose (vendor, sos_id) is not conflicted. QUEUED only — no attach. When
    `agents_factory` is given, a candidate-filtered 3rd stream fills the
    natural-person-agent flag; absent → `not_staged` (the flag is waived, never
    fabricated)."""
    p1 = resolve_pass1(vendor_orgs, filings_factory())
    conflicted = conflict_pass2(filings_factory(), p1["hit_pairs"], p1["vinfo"])
    candidates = [h for h in p1["hits"]
                  if (h["vendor_ref"], h["sos_ref"]["sos_id"]) not in conflicted]
    conflicts = [{"vendor_ref": vid, "sos_id": sos_id, "reason": "casos_row_conflict"}
                 for vid, sos_id in sorted(conflicted)]
    stats = dict(p1["stats"], candidates=len(candidates), conflicts=len(conflicts))
    if agents_factory is not None:
        stats["individual_agent_count"] = attach_individual_agent_flags(candidates, agents_factory())
        stats["individual_agent_status"] = "applied"
    else:
        stats["individual_agent_status"] = "not_staged"
    return {"candidates": candidates, "conflicts": conflicts, "stats": stats,
            "same_as_edges": [], "assertions": []}


def build_sos_attach(
    candidate,
    vendor_ref,
    *,
    reviewer,
    decided_at,
    policy_version=POLICY_VERSION,
    policy_hash=None,
    eligibility_snapshot_hash=None,
):
    """For an operator-APPROVED sos_id candidate, build (assertion, SAME_AS) —
    mirrors Phase-B `build_ein_attach`. subject = the `org-casos-<sos_id>` key
    anchor (carrying sos_id), target = the vendor; basis `operator_approved_sos_id`;
    SAME_AS anchor → vendor citing the assertion id. The assertion alone writes the
    ledger row; the SAME_AS is what `export_existing_orgs --enriched` reads to
    surface the vendor's `sos_id`."""
    return build_identity_attach(
        identity_key_entry("sos_id", "self"),
        candidate,
        vendor_ref,
        reviewer=reviewer,
        decided_at=decided_at,
        policy_version=policy_version,
        policy_hash=policy_hash,
        eligibility_snapshot_hash=eligibility_snapshot_hash,
    )


def coverage_report(resolve_output, vendor_orgs) -> dict[str, Any]:
    """Honest coverage + blocker diagnostics (Pre 10): tier split, token-vs-compact
    (did the compact key add anything?), needs-careful-review, reused sos_ids,
    conflicts, pool shape, individual-agent status."""
    cands = resolve_output["candidates"]
    stats = resolve_output["stats"]
    vendor_by_id = {v["id"]: v for v in vendor_orgs}
    per_vendor: dict[str, int] = defaultdict(int)
    sos_to_vendors: dict[str, set[str]] = defaultdict(set)
    exact = difflib_tier = ncr = token_matched = compact_only = 0
    for c in cands:
        vid = c["vendor_ref"]
        per_vendor[vid] += 1
        sos_to_vendors[c["sos_ref"]["sos_id"]].add(vid)
        if "normalized_name_exact" in c.get("signals", []):
            exact += 1
        else:
            difflib_tier += 1
        if c.get("needs_careful_review"):
            ncr += 1
        v = vendor_by_id.get(vid)
        sos_name = c["sos_ref"].get("display_label", "")
        if v and significant_tokens(v["display_label"]) & significant_tokens(sos_name):
            token_matched += 1
        else:
            compact_only += 1
    counts = sorted(per_vendor.values())

    def _pct(p: float) -> int:
        return counts[min(len(counts) - 1, int(p * len(counts)))] if counts else 0

    return {
        "vendor_orgs_total": len(vendor_orgs),
        "with_sos_candidate": len(per_vendor),
        "exact_tier": exact,
        "difflib_tier": difflib_tier,
        "needs_careful_review": ncr,
        "token_matched": token_matched,
        "compact_only": compact_only,
        "sos_id_reused_across_vendors": sum(1 for vs in sos_to_vendors.values() if len(vs) > 1),
        "conflicts": len(resolve_output["conflicts"]),
        "individual_agent_status": stats.get("individual_agent_status"),
        "individual_agent_count": stats.get("individual_agent_count"),
        "rows_scanned": stats["rows_scanned"],
        "block_pairs_evaluated": stats["block_pairs_evaluated"],
        "resolver_pairs_evaluated": stats["resolver_pairs_evaluated"],
        "max_per_vendor_hits": max(counts) if counts else 0,
        "p95_per_vendor_hits": _pct(0.95),
    }


def main(argv: list[str] | None = None) -> int:
    """Pure build: write QUEUED vendor→sos_id candidates + coverage for operator
    review. NO attach/dedup/load (operator steps). A redaction sweep
    (`scan_for_forbidden`) gates every artifact before it is written.

    Operator approve→attach runbook: for each APPROVED candidate, call
    `build_sos_attach(candidate, vendor_ref, reviewer=..., decided_at=...)` →
    append the assertion to the ledger + draw the SAME_AS; re-export enriched
    (`export_existing_orgs --enriched`) so the vendor surfaces its `sos_id`; then
    run the shipped dedup so vendor↔existing-firm collapse by hard key."""
    import argparse
    import json

    p = argparse.ArgumentParser(description="County Attribution Phase C — propose vendor sos_ids (queued)")
    p.add_argument("--vendors-inline", help="JSON list of {id, display_label} (testing/small)")
    p.add_argument("--input", type=Path, help="delegated-contracts.csv")
    p.add_argument("--approved", type=Path, help="approved-resolutions.jsonl (the 43)")
    p.add_argument("--filings", type=Path, required=True, help="CA-SOS Filings.csv")
    p.add_argument("--agents", type=Path, help="CA-SOS Agents.csv (optional — natural-person-agent flag)")
    p.add_argument("--out-dir", type=Path, required=True, help="review output dir")
    args = p.parse_args(argv)

    if args.vendors_inline:
        vendors = json.loads(args.vendors_inline)
    else:
        if not (args.input and args.approved):
            p.error("provide --vendors-inline OR both --input and --approved")
        from enrich_county_vendor_eins import _load_vendor_orgs  # consumed (Phase-B loader)
        vendors = _load_vendor_orgs(args.input, args.approved)

    def filings_factory():
        return open(args.filings, encoding="utf-8", errors="replace")

    agents_factory = None
    if args.agents:
        def agents_factory():  # noqa: E306
            return open(args.agents, encoding="utf-8", errors="replace")

    out = resolve_vendor_sos(vendors, filings_factory, agents_factory=agents_factory)
    report = coverage_report(out, vendors)

    violations = scan_for_forbidden(out["candidates"]) + scan_for_forbidden(out["conflicts"]) + scan_for_forbidden(report)
    if violations:
        raise SystemExit(f"REDACTION VIOLATION (refusing to write): {violations[:5]}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vendor-sos-candidates.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out["candidates"]), encoding="utf-8")
    (out_dir / "conflicts.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out["conflicts"]), encoding="utf-8")
    (out_dir / "coverage.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("QUEUED only — NO sos_id attached. Operator: review the candidates, then build_sos_attach "
          "each APPROVED one (assertion + SAME_AS) → ledger → re-export enriched → dedup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
