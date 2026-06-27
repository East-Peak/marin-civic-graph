"""enrich_fppc_keys.py — Open Marin Identity Enrichment, Lane 3 (`committee_id`).

Attaches the FPPC committee id (the CA SOS Cal-Access FILER_ID) as a hard
identity key to campaign-committee `Organization` (`org-*`) contributor nodes,
so the shipped graph-org-dedup deterministic tier merges name-variant committee
dups and keeps different-election-cycle committees DISTINCT (Bonta-AG-2022 vs
-2026 carry different FPPC ids). Third lane on the shipped machinery (Lane 1 EIN
`enrich_org_keys`, Lane 2 CA-SOS `enrich_casos_keys`); `org_resolution.py` is
NEVER edited — the `committee_id` normalizer is registered at runtime.

Sources (both read from disk; no network/DB in the loop):
  - tier 1: the `committee-netfile-*` filer nodes in the normalized campaign
    bundle already carry `netfile_filer_id` = the FPPC committee id.
  - tier 2: an operator-staged Cal-Access `FILERNAME_CD` extract (committee
    registry) for state committees + name aliases.

The lane proposes name(+election-year)-gated `committee_id` candidates; the
operator approves; approval attaches `committee_id` via the Identity Control A
ledger. A NAME match NEVER attaches a key without audited approval, and the lane
NEVER collapses two distinct FILER_IDs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from org_resolution import KEY_NORMALIZERS, propose_org_resolutions
from identity_key_normalizers import _normalize_committee_id  # shared; Goal 0 re-export
from identity_ledger import read_assertions, write_assertions
from enrich_org_keys import assertion_for_approved_candidate

POLICY_VERSION = "fppc-lane-v1"

_YEAR_TOKEN = re.compile(r"\b(?:19|20)\d{2}\b")

# Synthetic FPPC key-anchor id prefix (mirrors Lane 1 `org-bmf-ein-*` / Lane 2
# `org-casos-*`). An approved attach links `org-fppc-<committee_id>` to the real
# `org-*`. Registered in the exporter's trusted prefixes + dedup's anchor set.
FPPC_ANCHOR_PREFIX = "org-fppc-"


# _normalize_committee_id is re-exported from identity_key_normalizers (Goal 0 —
# the single shared home for the key normalizers; imported above).
# register_committee_id_normalizer registers that shared callable into KEY_NORMALIZERS.


def register_committee_id_normalizer() -> None:
    """Idempotently register `_normalize_committee_id` under `"committee_id"` in
    the shared `KEY_NORMALIZERS`. Refuses to clobber a foreign registration (a
    stray mutation fails loud rather than silently winning). Called by every
    module that uses the key — `org_resolution.py` itself is never edited."""
    existing = KEY_NORMALIZERS.get("committee_id")
    if existing is None:
        KEY_NORMALIZERS["committee_id"] = _normalize_committee_id
    elif existing is not _normalize_committee_id:
        raise RuntimeError(
            "KEY_NORMALIZERS['committee_id'] is already registered to a different "
            f"callable ({existing!r}); refusing to clobber it"
        )


# ---------------------------------------------------------------------------
# Election-year token — the ONLY election_year source (Predeclared 4, Codex r2):
# a name-token regex. NEVER MoneyFlow.source_year (that's report year). A name
# with no year, or with >1 distinct year, yields None (ambiguous → withhold).
# ---------------------------------------------------------------------------


def _election_year(name: str) -> str | None:
    years = set(_YEAR_TOKEN.findall(name or ""))
    return next(iter(years)) if len(years) == 1 else None


# ---------------------------------------------------------------------------
# Tier 1 — filer spine (Predeclared 2). The `committee-netfile-*` nodes in the
# normalized campaign bundle already carry netfile_filer_id = the FPPC id.
# ---------------------------------------------------------------------------

_FILER_PREFIX = "committee-netfile-"


def filer_spine_refs(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keyed committee refs from `committee-netfile-*` Committee nodes (Pending
    skipped; non-committee nodes ignored). Each ref carries the normalized
    `committee_id`, display label, committee_type, and name-derived election_year."""
    refs: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("node_type") != "Committee" or not node.get("id", "").startswith(_FILER_PREFIX):
            continue
        props = node.get("properties", {})
        committee_id = _normalize_committee_id(props.get("netfile_filer_id"))
        if committee_id is None:
            continue  # "Pending"/unset — no FPPC id yet
        name = node.get("display_label") or props.get("name") or node["id"]
        refs.append({
            "committee_id": committee_id,
            "display_label": name,
            "committee_type": props.get("committee_type"),
            "election_year": _election_year(name),
            "source": "filer_spine",
        })
    return refs


def load_filer_spine(nodes_path: Path) -> list[dict[str, Any]]:
    """Filer spine from a normalized campaign bundle's nodes.jsonl on disk."""
    nodes = [
        json.loads(line)
        for line in Path(nodes_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return filer_spine_refs(nodes)


# ---------------------------------------------------------------------------
# Tier 2 — Cal-Access FILERNAME_CD (Predeclared 2/3). Operator-staged; the loop
# consumes a staged extract or a committed fixture (NEVER fetches). CP1252
# decode; allowlist committee FILER_TYPEs (NOT lobbying/individual); PRESERVE
# every (FILER_ID, NAML) alias as a matchable name (latest EFFECT_DT is display
# only — old aliases match historical contribution names).
# ---------------------------------------------------------------------------

# Committee-relevant FILER_TYPE descriptions (allowlist, NOT denylist — an
# unrecognized type is excluded). VERIFY against FILER_TYPES_CD.DESCRIPTION when
# staging the real dbwebexport (the exact strings can drift; this is a tunable
# constant, not a hard contract).
_CALACCESS_COMMITTEE_FILER_TYPES: frozenset[str] = frozenset({
    "RECIPIENT COMMITTEE", "CANDIDATE", "CANDIDATE/OFFICEHOLDER",
    "MAJOR DONOR", "INDEPENDENT EXPENDITURE COMMITTEE",
    "SLATE MAILER ORGANIZATION", "PROPONENT",
})


def parse_filername(path: Path, *, allowlist: frozenset[str] | None = None) -> list[dict[str, Any]]:
    """Parse a Cal-Access FILERNAME_CD extract (CP1252, tab-delimited, header
    row) into committee refs — one per (FILER_ID, NAML) alias row (all aliases
    preserved). Rows whose FILER_TYPE is not in the committee allowlist, or whose
    FILER_ID does not normalize to a clean committee_id, are dropped."""
    allow = allowlist if allowlist is not None else _CALACCESS_COMMITTEE_FILER_TYPES
    lines = Path(path).read_bytes().decode("cp1252").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    idx = {col: i for i, col in enumerate(header)}
    refs: list[dict[str, Any]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")

        def cell(col: str) -> str:
            i = idx.get(col)
            return cells[i].strip() if i is not None and i < len(cells) else ""

        if cell("FILER_TYPE").upper() not in allow:
            continue
        committee_id = _normalize_committee_id(cell("FILER_ID"))
        if committee_id is None:
            continue
        name = cell("NAML")
        refs.append({
            "committee_id": committee_id,
            "display_label": name,
            "filer_type": cell("FILER_TYPE"),
            "election_year": _election_year(name),
            "xref_filer_id": cell("XREF_FILER_ID") or None,
            "status": cell("STATUS") or None,
            "source": "cal_access",
        })
    return refs


# ---------------------------------------------------------------------------
# Year-gated resolution (Predeclared 3/4) — org-* contributor committees
# (name-only in source) -> committee_id, via the resolver's name signal GATED on
# election year. All proposals are `queued`; NONE auto-attached (cardinal rule);
# the lane NEVER proposes a candidate spanning two distinct FILER_IDs.
# ---------------------------------------------------------------------------


def resolve_committee_ids(
    org_nodes: list[dict[str, Any]], registry_refs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Propose `queued` committee_id candidates linking an `org-*` contributor
    committee to a `org-fppc-<committee_id>` anchor. YEAR GATE: an org only
    matches a registry ref whose election_year EQUALS the org's name-year (None
    matches None — a perennial committee; any year mismatch, incl. one-sided, is
    skipped). If exactly one committee_id matches it is proposed; 0 or >1
    (ambiguous) is WITHHELD — never a guess, never a cross-cycle collapse."""
    register_committee_id_normalizer()
    candidates: list[dict[str, Any]] = []
    for org in org_nodes:
        if org.get("node_type") != "Organization":
            continue
        org_name = org["display_label"]
        org_year = _election_year(org_name)
        matches: dict[str, list[dict[str, Any]]] = {}
        for ref in registry_refs:
            if org_year != ref.get("election_year"):
                continue  # YEAR GATE — cycle safety
            _edges, cands = propose_org_resolutions(
                [{"id": org["id"], "display_label": org_name}],
                [{"id": ref["committee_id"], "display_label": ref["display_label"]}],
                identity_keys=(),
            )
            if cands:
                matches.setdefault(ref["committee_id"], []).append(cands[0])
        if len(matches) != 1:
            continue  # 0 = no match; >1 = ambiguous -> withhold
        committee_id, hits = next(iter(matches.items()))
        best = max(hits, key=lambda c: c.get("confidence", 0))
        # convention (EIN/sos/County): subject = the new key anchor, candidate =
        # the existing org. SAME_AS (anchor -> org) + the approved assertion follow.
        candidates.append({
            "subject_ref": FPPC_ANCHOR_PREFIX + committee_id,
            "candidate_ref": org["id"],
            "committee_id": committee_id,
            "signals": best["signals"],
            "confidence": best.get("confidence"),
            "status": "queued",
            "election_year": org_year,
            "evidence_record_ids": [],
            "source": "fppc_committee_id",
        })
    return sorted(candidates, key=lambda c: (c["candidate_ref"], c["committee_id"]))


# ---------------------------------------------------------------------------
# Approve flow (Predeclared 5, Codex r1 blocker). build_attach.py builds all
# attaches at once and write_assertions-OVERWRITES, so a 3rd lane needs a
# read-merge-write that PRESERVES the existing ledger rows.
# ---------------------------------------------------------------------------


def merge_approved_assertions(
    new_assertions: list[dict[str, Any]], ledger_path: Path
) -> list[dict[str, Any]]:
    """Read the existing ledger, add `new_assertions`, write back — PRESERVING
    every existing row (the live key-attach assertions must survive byte-for-byte).
    De-dup by assertion id: an exact-payload duplicate is a no-op; the SAME id
    with a DIFFERENT payload FAILS LOUD (assertion ids exclude reviewer/date/
    evidence, so a divergent payload is a real conflict, never a silent mutation)."""
    ledger_path = Path(ledger_path)
    by_id = {a["id"]: a for a in read_assertions(ledger_path)}
    for assertion in new_assertions:
        aid = assertion["id"]
        prior = by_id.get(aid)
        if prior is None:
            by_id[aid] = assertion
        elif json.dumps(prior, sort_keys=True) != json.dumps(assertion, sort_keys=True):
            raise ValueError(
                f"assertion {aid} already exists with a DIFFERENT payload — "
                "refusing to mutate the ledger (fix the conflict explicitly)"
            )
        # else: exact duplicate -> no-op
    merged = list(by_id.values())
    write_assertions(merged, ledger_path)
    return merged


def build_committee_attach(
    candidate: dict[str, Any],
    real_org_ref: dict[str, Any],
    *,
    reviewer: str,
    decided_at: str,
    policy_version: str = POLICY_VERSION,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """For an operator-APPROVED committee_id candidate, build (assertion, SAME_AS
    edge) — mirroring build_attach.py: subject = the `org-fppc-<id>` key anchor
    (carrying committee_id + entity_class committee), target = the real `org-*`;
    basis `operator_approved_committee_id`; SAME_AS anchor -> org citing the
    assertion id. Reuses the shipped `assertion_for_approved_candidate`."""
    anchor_id = candidate["subject_ref"]
    committee_id = candidate["committee_id"]
    subject = {
        "id": anchor_id,
        "display_label": real_org_ref.get("display_label", anchor_id),
        "committee_id": committee_id,
        "entity_class": "committee",
        "source": "fppc",
    }
    target = real_org_ref if real_org_ref.get("id") else {"id": candidate["candidate_ref"]}
    assertion = assertion_for_approved_candidate(
        candidate, subject=subject, target=target,
        basis="operator_approved_committee_id",
        reviewer=reviewer, decided_at=decided_at, policy_version=policy_version,
    )
    same_as = {
        "source_id": anchor_id,
        "target_id": candidate["candidate_ref"],
        "relationship_type": "SAME_AS",
        "properties": {"basis": "operator_approved_committee_id", "assertion_id": assertion["id"]},
    }
    return assertion, same_as


# ---------------------------------------------------------------------------
# ROI preflight + coverage honesty (Predeclared 9, Codex r1). Reports how much
# of the org-* committee universe the lane can key, before any approval.
# ---------------------------------------------------------------------------


def roi_preflight(
    org_nodes: list[dict[str, Any]], registry_refs: list[dict[str, Any]]
) -> dict[str, int]:
    """Coverage report: org-* committee nodes, registry refs, year-gated
    committee_id candidates, and the keyable / unkeyed split. No silent
    truncation — the unkeyed remainder stays in the dedup name-tier queue."""
    candidates = resolve_committee_ids(org_nodes, registry_refs)
    keyable = {c["candidate_ref"] for c in candidates}
    org_ids = {o["id"] for o in org_nodes if o.get("node_type") == "Organization"}
    return {
        "org_nodes": len(org_ids),
        "registry_refs": len(registry_refs),
        "committee_id_candidates": len(candidates),
        "orgs_keyable": len(keyable),
        "orgs_unkeyed": len(org_ids - keyable),
    }
