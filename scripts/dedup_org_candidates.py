"""dedup_org_candidates.py — graph-internal Organization dedup for Open Marin.

Collapses duplicate `:Organization` nodes safely. NOT a new subsystem: it is the
existing resolver (`org_resolution.propose_org_resolutions`) + the Identity
Control A assertion ledger (`identity_ledger`) pointed INWARD (org<->org within
the graph) instead of cross-source. Three layers:

  1. Candidate generation (this pass — PROPOSES, never merges). Reads the
     enriched org export, excluding synthetic key anchors + already-tombstoned
     refs. Two tiers by DIFFERENT mechanisms:
       - Deterministic = GROUP-BY-KEY: real refs grouped by normalized
         ein/uei/sos_id; a same-class group of size >1 -> `deterministic`
         `org_dedup_key_exact` assertions written directly via make_assertion
         (NOT propose_org_resolutions, which conflict-queues N>=2 same-key refs).
       - Name = the resolver, pairwise: propose_org_resolutions on disjoint N=2
         name-blocked pairs -> `queued` candidates, NEVER merged.
     False-friend defense: a name-derived structural-class mismatch
     (committee vs organization) is never a candidate; an affiliate-token
     divergence (Foundation/Fund/PAC/.../Friends of) tags the candidate
     `needs_careful_review`.
  2. Adjudication — human-gated, through the ledger (operator approves/rejects).
  3. Application — a reversible, operator-gated merge applier (separate units).

Pure: reads the export, writes ledger candidates + a sidecar to its OWN files
(data/identity/dedup-assertions.jsonl — NEVER assertions.jsonl, which
write_assertions overwrites whole). No graph write. `org_resolution.py` +
Identity Control A modules are consumed, never edited.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from org_resolution import KEY_NORMALIZERS, propose_org_resolutions  # noqa: F401
from enrich_casos_keys import register_sos_id_normalizer
from identity_ledger import make_assertion, write_assertions

# Synthetic identity-anchor key nodes — NOT real orgs; excluded from candidates.
ANCHOR_PREFIXES: tuple[str, ...] = ("org-bmf-ein-", "org-casos-", "org-usasp-uei-")

# Name-derived structural class (the enriched export carries no entity_class).
# A committee/PAC token => `committee`, else `organization`. Word-boundary
# matched so "Committee" matches but "Coalition" does not.
_COMMITTEE_TOKENS: tuple[str, ...] = (
    "political action committee", "committee", "bapac", "bpac", "pac",
)

# Affiliate tokens — a one-sided presence flags likely-distinct affiliates
# (an org vs its Foundation/Friends-of/PAC/auxiliary) for careful review.
_AFFILIATE_TOKENS: tuple[str, ...] = (
    "foundation", "fund", "endowment", "auxiliary", "friends of",
    "pac", "bpac", "bapac", "pta", "pto",
)


def is_anchor(org_id: str) -> bool:
    """True for a synthetic key-anchor id (org-bmf-ein-*/org-casos-*/org-usasp-uei-*)."""
    return org_id.startswith(ANCHOR_PREFIXES)


def load_org_refs(export_path: Path) -> list[dict[str, Any]]:
    """Load the enriched org export, excluding synthetic key anchors AND
    already-tombstoned refs (`dedup_superseded_by` set) — a merged dup never
    re-enters the candidate pass (the merge sticks)."""
    data = json.loads(Path(export_path).read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else next(
        v for v in data.values() if isinstance(v, list)
    )
    return [
        r for r in rows
        if not is_anchor(r["id"]) and r.get("dedup_superseded_by") is None
    ]


def _norm_tokens(name: str) -> str:
    """Casefold + collapse non-alphanumeric runs to single spaces (for token
    membership tests). Padded with spaces so word-boundary matching is simple."""
    return " " + re.sub(r"[^0-9a-z]+", " ", name.casefold()).strip() + " "


def structural_class(name: str) -> str:
    """`committee` if the name carries a committee/PAC token, else `organization`."""
    padded = _norm_tokens(name)
    for token in _COMMITTEE_TOKENS:
        if f" {token} " in padded:
            return "committee"
    return "organization"


def _affiliate_tokens_present(name: str) -> frozenset[str]:
    padded = _norm_tokens(name)
    return frozenset(t for t in _AFFILIATE_TOKENS if f" {t} " in padded)


def affiliate_token_divergence(name_a: str, name_b: str) -> bool:
    """True iff one name carries an affiliate token the other lacks (one-sided).
    Both-carry or neither-carry => not divergent."""
    a, b = _affiliate_tokens_present(name_a), _affiliate_tokens_present(name_b)
    return bool(a ^ b)


# ---------------------------------------------------------------------------
# Deterministic tier — GROUP-BY-KEY (Predeclared 1). NOT propose_org_resolutions
# (which conflict-queues N>=2 same-key refs). Same-class guard: a shared key
# never overrides a committee<->organization mismatch (Predeclared 4).
# ---------------------------------------------------------------------------

_DEDUP_KEYS: tuple[str, ...] = ("ein", "uei", "sos_id")
DEDUP_KEY_BASIS = "org_dedup_key_exact"


def deterministic_dedup_assertions(
    refs: list[dict[str, Any]], *, reviewer: str, policy_version: str
) -> list[dict[str, Any]]:
    """`deterministic` `org_dedup_key_exact` assertions for same-key, same-class
    org groups of size >1. Each group becomes a STAR from its lexically-smallest
    member (N-1 assertions, subject<target) — enough to form one component in
    assembly. Written directly via make_assertion (no resolver, no egress gate).
    Calls register_sos_id_normalizer() first so the sos_id key resolves."""
    register_sos_id_normalizer()
    refs_by_id = {r["id"]: r for r in refs}

    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in refs:
        for key in _DEDUP_KEYS:
            value = KEY_NORMALIZERS[key](r.get(key))
            if value is not None:
                groups[(key, value)].append(r["id"])

    assertions: dict[str, dict[str, Any]] = {}
    for (_key, _value), ids in sorted(groups.items()):
        if len(set(ids)) < 2:
            continue
        by_class: dict[str, list[str]] = defaultdict(list)
        for oid in ids:
            by_class[structural_class(refs_by_id[oid]["display_label"])].append(oid)
        for _cls, members in sorted(by_class.items()):
            members = sorted(set(members))
            if len(members) < 2:
                continue  # same-class guard: a lone member of a class never merges
            pivot = members[0]
            for other in members[1:]:
                subject_ref, target_ref = sorted((pivot, other))
                a = make_assertion(
                    subject_ref=subject_ref,
                    target_ref=target_ref,
                    status="deterministic",
                    basis=DEDUP_KEY_BASIS,
                    subject=refs_by_id[subject_ref],
                    target=refs_by_id[target_ref],
                    reviewer=reviewer,
                    decided_at="deterministic",
                    policy_version=policy_version,
                )
                assertions[a["id"]] = a
    return sorted(assertions.values(), key=lambda a: a["id"])


# ---------------------------------------------------------------------------
# Canonical-node selection (Predeclared 3) — deterministic + pinned.
# (a) a node carrying a hard key beats one without; (b) tie -> highest degree
# (null/missing degree sorts as 0 — a thin synthetic anchor never wins);
# (c) tie -> lexically-smallest id.
# ---------------------------------------------------------------------------


def _has_hard_key(ref: dict[str, Any]) -> bool:
    return any(ref.get(key) for key in _DEDUP_KEYS)


def _degree(ref: dict[str, Any]) -> int:
    value = ref.get("degree")
    return value if isinstance(value, int) else 0  # null/missing/non-int -> 0


def choose_canonical(refs: list[dict[str, Any]]) -> str:
    """The surviving node's id for a cluster: hard-key > degree > lexical id."""
    return min(
        refs, key=lambda r: (not _has_hard_key(r), -_degree(r), r["id"])
    )["id"]


# ---------------------------------------------------------------------------
# Component assembly (Predeclared 5, 10) — connected components of MERGE-intent
# (deterministic/approved) dedup-basis assertions. A component is REFUSED (never
# a silent over-merge) if it contains an anchor, a rejected_entity_distinct pair
# (the SPLIT guard), or >1 distinct value for the same hard key.
# ---------------------------------------------------------------------------

_MERGE_STATUSES: frozenset[str] = frozenset({"deterministic", "approved"})


def assemble_components(
    assertions: list[dict[str, Any]], refs_by_id: dict[str, dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Partition merge-intent assertions into accepted components (each with a
    chosen canonical) and refused components (each with reasons). Only
    `deterministic`/`approved` dedup-basis assertions form components; an
    un-approved (e.g. `queued`) pair never rides transitivity.
    `rejected_entity_distinct` pairs are read by STATUS for the SPLIT guard."""
    register_sos_id_normalizer()
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    rejected: set[frozenset[str]] = set()
    nodes: set[str] = set()
    for a in assertions:
        # Predeclared 10: assembly reads ONLY dedup-basis (org_dedup_*) rows.
        # The live key-attach assertions (basis operator_approved_ein/sos_id,
        # status approved) are a SEPARATE namespace — ignored, never a merge.
        if not str(a.get("basis", "")).startswith("org_dedup"):
            continue
        subject, target = a["subject_ref"], a["target_ref"]
        if a["status"] in _MERGE_STATUSES:
            nodes.update((subject, target))
            union(subject, target)
        elif a["status"] == "rejected_entity_distinct":
            rejected.add(frozenset((subject, target)))

    components: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        components[find(node)].append(node)

    accepted: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for members in components.values():
        members = sorted(set(members))
        member_set = set(members)
        reasons: list[str] = []
        if any(is_anchor(m) for m in members):
            reasons.append("contains_anchor")
        if any(pair <= member_set for pair in rejected):
            reasons.append("rejected_pair")
        for key in _DEDUP_KEYS:
            values = {
                KEY_NORMALIZERS[key](refs_by_id[m].get(key))
                for m in members if m in refs_by_id
            }
            values.discard(None)
            if len(values) > 1:
                reasons.append(f"hard_key_conflict:{key}")
                break
        if reasons:
            refused.append({"members": members, "reasons": reasons})
        else:
            accepted.append({
                "members": members,
                "canonical": choose_canonical([refs_by_id[m] for m in members]),
            })
    return {
        "accepted": sorted(accepted, key=lambda c: c["members"]),
        "refused": sorted(refused, key=lambda c: c["members"]),
    }


# ---------------------------------------------------------------------------
# Name tier — the resolver, pairwise on name-blocked N=2 pairs (Predeclared 1).
# Queued, NEVER merged. Class-mismatch + shared-key pairs are excluded; an
# affiliate-token divergence routes the candidate to needs_careful_review.
# ---------------------------------------------------------------------------


def _key_set(ref: dict[str, Any]) -> set[tuple[str, str]]:
    """Normalized (key, value) pairs the ref carries — for shared-key exclusion."""
    out: set[tuple[str, str]] = set()
    for key in _DEDUP_KEYS:
        value = KEY_NORMALIZERS[key](ref.get(key))
        if value is not None:
            out.add((key, value))
    return out


def _first_token(name: str) -> str:
    tokens = re.sub(r"[^0-9a-z]+", " ", name.casefold()).split()
    return tokens[0] if tokens else ""


def name_tier_candidates(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`queued` name-signal candidates from `propose_org_resolutions` over disjoint
    N=2 pairs, blocked by first normalized name token (bounds the comparison).
    Excludes: self-pairs, symmetric dups, committee<->organization class
    mismatches, and pairs sharing a hard key (the deterministic tier's job). An
    affiliate-token divergence tags the candidate `needs_careful_review`."""
    register_sos_id_normalizer()
    keys_by_id = {r["id"]: _key_set(r) for r in refs}

    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in refs:
        token = _first_token(r["display_label"])
        if token:
            blocks[token].append(r)

    out: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for _token, members in sorted(blocks.items()):
        members = sorted(members, key=lambda r: r["id"])
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if a["id"] == b["id"]:
                    continue
                pair = (a["id"], b["id"])  # a.id < b.id (sorted) — canonical
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if structural_class(a["display_label"]) != structural_class(b["display_label"]):
                    continue  # class mismatch — never a candidate
                if keys_by_id[a["id"]] & keys_by_id[b["id"]]:
                    continue  # shared hard key — deterministic tier handles it
                _edges, cands = propose_org_resolutions([a], [b], identity_keys=())
                divergent = affiliate_token_divergence(
                    a["display_label"], b["display_label"]
                )
                for cand in cands:
                    enriched = dict(cand)
                    enriched["affiliate_token_divergence"] = divergent
                    enriched["review_tier"] = (
                        "needs_careful_review" if divergent else "standard"
                    )
                    out.append(enriched)
    return sorted(out, key=lambda c: (c["subject_ref"], c["candidate_ref"]))


# ---------------------------------------------------------------------------
# Orchestration — pure pass: write to the dedup ledger's OWN files. NEVER
# assertions.jsonl (write_assertions overwrites whole → would wipe the live
# key-attach ledger). No graph write (Predeclared 2).
# ---------------------------------------------------------------------------

DEFAULT_DEDUP_LEDGER = Path("data/identity/dedup-assertions.jsonl")
DEFAULT_SIDECAR = Path("data/review/dedup-name-candidates.jsonl")


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
    )


def run_dedup_pass(
    export_path: Path,
    *,
    dedup_ledger_path: Path,
    sidecar_path: Path,
    reviewer: str,
    policy_version: str,
) -> dict[str, Any]:
    """Pure pass: read the enriched export, write `deterministic` dedup
    assertions to the SEPARATE dedup ledger and `queued` name candidates to the
    sidecar. Never touches assertions.jsonl; no graph write."""
    refs = load_org_refs(export_path)
    deterministic = deterministic_dedup_assertions(
        refs, reviewer=reviewer, policy_version=policy_version
    )
    candidates = name_tier_candidates(refs)
    write_assertions(deterministic, Path(dedup_ledger_path))
    _write_jsonl(candidates, Path(sidecar_path))
    return {
        "org_refs": len(refs),
        "deterministic_assertions": len(deterministic),
        "name_candidates": len(candidates),
        "needs_careful_review": sum(
            1 for c in candidates if c.get("review_tier") == "needs_careful_review"
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Graph-internal Organization dedup candidate pass (PROPOSES, never merges)."
    )
    parser.add_argument("--export", required=True, type=Path,
                        help="Enriched org export (existing-orgs-enriched.json).")
    parser.add_argument("--dedup-ledger", type=Path, default=DEFAULT_DEDUP_LEDGER,
                        help="Separate dedup-assertions.jsonl (NEVER assertions.jsonl).")
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR,
                        help="Name-candidate review sidecar.")
    parser.add_argument("--reviewer", default="dedup_pass")
    parser.add_argument("--policy-version", default="dedup-v1")
    args = parser.parse_args(argv)
    summary = run_dedup_pass(
        args.export,
        dedup_ledger_path=args.dedup_ledger,
        sidecar_path=args.sidecar,
        reviewer=args.reviewer,
        policy_version=args.policy_version,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
