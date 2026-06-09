"""Spec §3 edge name → live AuraDB edge name(s) mapping.

Single source of truth for the v1 design's §3 relationship ontology against the
current live projection, extended by the COI spec §4.1 Membership edges
(MEMBER, MEMBER_OF_ORG — M2a). Consumed by:

- `scripts/build_signature_subgraphs.py` — Phase-2 whitelist for 2-hop traversal
- `app/src/lib/edge-vocabulary.ts` — TypeScript mirror for the radial-hero (Plan 2 Batch D)
- `app/src/lib/server/entity-loader.ts` — per-focus must-show + Phase-2 fill queries

The live catalog (source of these mappings) lives in
`docs/reference/2026-04-19-live-edge-catalog.md`.

**Discrepancies (spec §3 → live):**

Renamed (same semantic, different live name):
  ABOUT_ITEM      → ABOUT_AGENDA_ITEM
  DISCLOSED_IN    → DISCLOSED_IN_FILING
  AMENDS          → AMENDS_AGREEMENT
  RESULT_OF       → RESULT_OF_ELECTION
  BY_PERSON       → CANDIDATE_ACTOR
  BETWEEN         → COUNTERPARTY_ACTOR

Split by source/target type:
  PART_OF         → PART_OF_MEETING (AgendaItem→Meeting), PART_OF_CASE (Proceeding→Case)
  FILED_BY        → FILED_BY (Person), FILED_BY_COMMITTEE, OFFICIAL_FILER
  CONTROLLED_BY   → CONTROLLED_BY, CONTROLLED_BY_COMMITTEE (Candidacy side)
  HEARD_IN        → HEARD_IN (Case), HEARD_BY (Proceeding)
  IN_ELECTION     → FILED_FOR_ELECTION, RELATED_TO_ELECTION

Weak-family collapses (the live graph only has the weak variant):
  FOR_PROJECT     → RELATES_TO_PROJECT
  ABOUT_PROJECT   → RELATES_TO_PROJECT
  ABOUT_PROGRAM   → RELATES_TO_PROGRAM
  UNDER_AGREEMENT → RELATES_TO_AGREEMENT

Not yet materialized (empty list — queries referencing it match nothing, which
is the correct behavior until ingestion lands):
  CONSTRAINS      → []

In addition to the spec §3 edges above, `PHASE2_WHITELIST_LIVE` carries several
live-only edges that are load-bearing for entity pages:

- OPERATED_BY          — Program → operating institution
- FILED_WITH           — Filing → receiving agency
- FILED_DURING_SEAT_SERVICE, FILED_FOR_SEAT — Form 700/803 filings → tenure/seat
- PRIMARY_FOR_ELECTION — Committee ↔ Election (primary election linkage)
- PRIMARY_PLACE        — Project → primary place
- DECIDED_AT           — Decision → Meeting (redundant with AT_MEETING but both exist)

Universal / structural edges (EVIDENCED_BY, IN_JURISDICTION, RELATES_TO_ISSUE,
plus the weak RELATES_TO_* family minus the three load-bearing exceptions) stay
in `UNIVERSAL_EDGES_LIVE` and are excluded from `PHASE2_WHITELIST_LIVE`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Spec §3 → live mapping
# ---------------------------------------------------------------------------

SPEC_TO_LIVE: dict[str, list[str]] = {
    # --- Governance -------------------------------------------------------
    "CAST_VOTE": ["CAST_VOTE"],
    "AT_MEETING": ["AT_MEETING", "DECIDED_AT"],
    "ABOUT_ITEM": ["ABOUT_AGENDA_ITEM"],
    "DECIDED_BY": ["DECIDED_BY"],
    "PART_OF": ["PART_OF_MEETING", "PART_OF_CASE"],
    "HELD_BY": ["HELD_BY"],
    "FOR_SEAT": ["FOR_SEAT"],
    "RESULT_OF": ["RESULT_OF_ELECTION"],
    "AT_INSTITUTION": ["AT_INSTITUTION"],
    # --- Money ------------------------------------------------------------
    "FROM_SOURCE": ["FROM_SOURCE"],
    "TO_TARGET": ["TO_TARGET"],
    "DISCLOSED_IN": ["DISCLOSED_IN_FILING"],
    # UNDER_AGREEMENT: no strong live edge. Weak RELATES_TO_AGREEMENT is the
    # only variant (MoneyFlow/Decision → Agreement).
    "UNDER_AGREEMENT": ["RELATES_TO_AGREEMENT"],
    "AMENDS": ["AMENDS_AGREEMENT"],
    # --- Committee / filing ----------------------------------------------
    "CONTROLLED_BY": ["CONTROLLED_BY", "CONTROLLED_BY_COMMITTEE"],
    "FILED_BY": ["FILED_BY", "FILED_BY_COMMITTEE", "OFFICIAL_FILER"],
    "BY_PERSON": ["CANDIDATE_ACTOR"],
    "IN_ELECTION": ["FILED_FOR_ELECTION", "RELATED_TO_ELECTION"],
    "FOR_ELECTION": ["FOR_ELECTION"],
    # --- Projects / programs / agreements --------------------------------
    # All four collapse to the weak RELATES_TO_* variant — the live graph has
    # no strong FOR_PROJECT / ABOUT_PROJECT / ABOUT_PROGRAM edge. Per Plan 2
    # Batch A (2026-04-19) these weak edges are kept in PHASE2_WHITELIST_LIVE
    # because removing them would leave Project/Program/Agreement pages empty.
    "FOR_PROJECT": ["RELATES_TO_PROJECT"],
    "ABOUT_PROJECT": ["RELATES_TO_PROJECT"],
    "ABOUT_PROGRAM": ["RELATES_TO_PROGRAM"],
    "BETWEEN": ["COUNTERPARTY_ACTOR"],
    # --- Legal ------------------------------------------------------------
    "PARTY_TO": ["PARTY_TO"],
    "CONSTRAINS": [],  # not yet materialized in live graph — correct behavior.
    "HEARD_IN": ["HEARD_IN", "HEARD_BY"],
    # --- COI / membership (COI spec §4.1, M2a) -----------------------------
    # Membership reifies a person↔org affiliation; both edges land live under
    # their spec names. Provenance uses the universal EVIDENCED_BY.
    "MEMBER": ["MEMBER"],
    "MEMBER_OF_ORG": ["MEMBER_OF_ORG"],
}

# ---------------------------------------------------------------------------
# Universal / structural edges — excluded from Phase 2 traversal
# ---------------------------------------------------------------------------

UNIVERSAL_EDGES_LIVE: list[str] = [
    # Core universals — spec §3 explicitly labels these structural.
    "EVIDENCED_BY",
    "IN_JURISDICTION",
    "RELATES_TO_ISSUE",
    # Weak RELATES_TO_* family — too universal/noisy for 2-hop traversal.
    # Exceptions: RELATES_TO_PROJECT, RELATES_TO_PROGRAM, RELATES_TO_AGREEMENT
    # are load-bearing (only live variant of spec §3 strong edges) and stay
    # in PHASE2_WHITELIST_LIVE.
    "RELATES_TO_ACTOR",
    "RELATES_TO_AGENDA_ITEM",
    "RELATES_TO_AMENDMENT",
    "RELATES_TO_CASE",
    "RELATES_TO_COMMITTEE",
    "RELATES_TO_DECISION",
    "RELATES_TO_ELECTION",  # distinct from RELATED_TO_ELECTION (Election↔Election)
    "RELATES_TO_FILING",
    "RELATES_TO_INSTITUTION",
    "RELATES_TO_MEETING",
    "RELATES_TO_MONEY_FLOW",
    "RELATES_TO_PLACE",
    "RELATES_TO_RECORD",
    "RELATES_TO_SEAT",
    # Record-lineage and validation edges — used by the evidence drawer, not
    # by the radial hero or signature-subgraph builder.
    "DERIVED_FROM_RECORD",
    "RECORD_ATTACHED_TO_RECORD",
    "RECORD_EXTRACTS_FROM_RECORD",
    "RECORD_AUTHORIZES_DECISION",
    "RECORD_INTRODUCES_DECISION",
    "SAME_AS",
    "VALIDATES",
]

# ---------------------------------------------------------------------------
# Phase 2 whitelist (live names)
# ---------------------------------------------------------------------------

# Spec §3 edges the builder must traverse (everything in SPEC_TO_LIVE except
# universals — CONSTRAINS stays listed but contributes [] until materialized).
_PHASE2_SPEC: list[str] = [
    "CAST_VOTE", "AT_MEETING", "ABOUT_ITEM", "DECIDED_BY", "PART_OF", "HELD_BY",
    "FOR_SEAT", "RESULT_OF", "AT_INSTITUTION", "FROM_SOURCE", "TO_TARGET",
    "DISCLOSED_IN", "UNDER_AGREEMENT", "AMENDS", "CONTROLLED_BY", "FILED_BY",
    "BY_PERSON", "IN_ELECTION", "FOR_ELECTION", "FOR_PROJECT", "ABOUT_PROJECT",
    "ABOUT_PROGRAM", "PARTY_TO", "CONSTRAINS", "BETWEEN", "HEARD_IN",
    # COI spec §4.1 (M2a): a Membership must be reachable from Person/Org
    # neighborhoods, so its edges are Phase-2 traversable.
    "MEMBER", "MEMBER_OF_ORG",
]

# Live-only edges with no direct spec §3 equivalent but needed for entity-page
# neighborhoods (see module docstring for rationale per edge).
_EXTRA_LIVE_PHASE2: list[str] = [
    "OPERATED_BY",
    "FILED_WITH",
    "FILED_DURING_SEAT_SERVICE",
    "FILED_FOR_SEAT",
    "PRIMARY_FOR_ELECTION",
    "PRIMARY_PLACE",
]


def _derive_phase2_whitelist() -> list[str]:
    universals = set(UNIVERSAL_EDGES_LIVE)
    result: set[str] = set()
    for spec_name in _PHASE2_SPEC:
        for live_name in SPEC_TO_LIVE.get(spec_name, []):
            if live_name not in universals:
                result.add(live_name)
    result.update(_EXTRA_LIVE_PHASE2)
    return sorted(result)


PHASE2_WHITELIST_LIVE: list[str] = _derive_phase2_whitelist()


# ---------------------------------------------------------------------------
# Edge-style classification
# ---------------------------------------------------------------------------

MONEY_EDGES_LIVE: list[str] = sorted({
    live
    for spec in ("FROM_SOURCE", "TO_TARGET", "DISCLOSED_IN", "UNDER_AGREEMENT")
    for live in SPEC_TO_LIVE[spec]
})

LEGAL_EDGES_LIVE: list[str] = sorted({
    live
    for spec in ("CONSTRAINS",)
    for live in SPEC_TO_LIVE[spec]
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def spec_to_live(spec_edge: str) -> list[str]:
    """Return the list of live AuraDB edge names for a spec §3 edge name.

    Returns an empty list if the spec name is unknown or has no live equivalent
    (e.g., CONSTRAINS, which is not yet materialized in the live projection).
    """
    return SPEC_TO_LIVE.get(spec_edge, [])


__all__ = [
    "SPEC_TO_LIVE",
    "PHASE2_WHITELIST_LIVE",
    "UNIVERSAL_EDGES_LIVE",
    "MONEY_EDGES_LIVE",
    "LEGAL_EDGES_LIVE",
    "spec_to_live",
]
