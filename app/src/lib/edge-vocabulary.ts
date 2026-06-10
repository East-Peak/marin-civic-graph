// TypeScript mirror of scripts/edge_vocabulary.py — the Python module is the
// source of truth. Any change must touch both or the v1 radial-hero neighborhood
// will drift from the spec → live mapping used by the signature-subgraph builder.
//
// See docs/reference/2026-04-19-live-edge-catalog.md for the live catalog that
// these mappings encode. See the Python module's docstring for the discrepancy
// commentary (renamed / split / weak-family collapses / not-yet-materialized).

// ---------------------------------------------------------------------------
// Spec §3 → live mapping
// ---------------------------------------------------------------------------

export const SPEC_TO_LIVE: Record<string, string[]> = {
  // --- Governance ----------------------------------------------------------
  CAST_VOTE: ["CAST_VOTE"],
  AT_MEETING: ["AT_MEETING", "DECIDED_AT"],
  ABOUT_ITEM: ["ABOUT_AGENDA_ITEM"],
  DECIDED_BY: ["DECIDED_BY"],
  PART_OF: ["PART_OF_MEETING", "PART_OF_CASE"],
  HELD_BY: ["HELD_BY"],
  FOR_SEAT: ["FOR_SEAT"],
  RESULT_OF: ["RESULT_OF_ELECTION"],
  AT_INSTITUTION: ["AT_INSTITUTION"],
  // --- Money --------------------------------------------------------------
  FROM_SOURCE: ["FROM_SOURCE"],
  TO_TARGET: ["TO_TARGET"],
  DISCLOSED_IN: ["DISCLOSED_IN_FILING"],
  // UNDER_AGREEMENT: no strong live edge; weak RELATES_TO_AGREEMENT is the
  // only variant (MoneyFlow/Decision → Agreement).
  UNDER_AGREEMENT: ["RELATES_TO_AGREEMENT"],
  AMENDS: ["AMENDS_AGREEMENT"],
  // --- Committee / filing -------------------------------------------------
  CONTROLLED_BY: ["CONTROLLED_BY", "CONTROLLED_BY_COMMITTEE"],
  // FILED_BY_ORG (M2b): Form 990 Filing → the filing Organization — the
  // org-filer variant, following the FILED_BY_COMMITTEE precedent.
  FILED_BY: ["FILED_BY", "FILED_BY_COMMITTEE", "OFFICIAL_FILER", "FILED_BY_ORG"],
  BY_PERSON: ["CANDIDATE_ACTOR"],
  IN_ELECTION: ["FILED_FOR_ELECTION", "RELATED_TO_ELECTION"],
  FOR_ELECTION: ["FOR_ELECTION"],
  // --- Projects / programs / agreements -----------------------------------
  // All four collapse to the weak RELATES_TO_* variant — the live graph has
  // no strong FOR_PROJECT / ABOUT_PROJECT / ABOUT_PROGRAM edge. Per Plan 2
  // Batch A these weak edges are kept in PHASE2_WHITELIST_LIVE because removing
  // them would leave Project/Program/Agreement pages empty.
  FOR_PROJECT: ["RELATES_TO_PROJECT"],
  ABOUT_PROJECT: ["RELATES_TO_PROJECT"],
  ABOUT_PROGRAM: ["RELATES_TO_PROGRAM"],
  BETWEEN: ["COUNTERPARTY_ACTOR"],
  // --- Legal --------------------------------------------------------------
  PARTY_TO: ["PARTY_TO"],
  CONSTRAINS: [], // not yet materialized in live graph — correct behavior.
  HEARD_IN: ["HEARD_IN", "HEARD_BY"],
  // --- COI / membership (COI spec §4.1, M2a) -------------------------------
  // Membership reifies a person↔org affiliation; both edges land live under
  // their spec names. Provenance uses the universal EVIDENCED_BY.
  MEMBER: ["MEMBER"],
  MEMBER_OF_ORG: ["MEMBER_OF_ORG"],
};

// ---------------------------------------------------------------------------
// Universal / structural edges — excluded from Phase 2 traversal
// ---------------------------------------------------------------------------

export const UNIVERSAL_EDGES_LIVE: string[] = [
  // Core universals — spec §3 explicitly labels these structural.
  "EVIDENCED_BY",
  "IN_JURISDICTION",
  "RELATES_TO_ISSUE",
  // Weak RELATES_TO_* family — too universal/noisy for 2-hop traversal.
  // Exceptions: RELATES_TO_PROJECT, RELATES_TO_PROGRAM, RELATES_TO_AGREEMENT
  // are load-bearing (only live variant of spec §3 strong edges) and stay
  // in PHASE2_WHITELIST_LIVE.
  "RELATES_TO_ACTOR",
  "RELATES_TO_AGENDA_ITEM",
  "RELATES_TO_AMENDMENT",
  "RELATES_TO_CASE",
  "RELATES_TO_COMMITTEE",
  "RELATES_TO_DECISION",
  "RELATES_TO_ELECTION", // distinct from RELATED_TO_ELECTION (Election↔Election)
  "RELATES_TO_FILING",
  "RELATES_TO_INSTITUTION",
  "RELATES_TO_MEETING",
  "RELATES_TO_MONEY_FLOW",
  "RELATES_TO_PLACE",
  "RELATES_TO_RECORD",
  "RELATES_TO_SEAT",
  // Record-lineage and validation edges — used by the evidence drawer, not
  // by the radial hero or signature-subgraph builder.
  "DERIVED_FROM_RECORD",
  "RECORD_ATTACHED_TO_RECORD",
  "RECORD_EXTRACTS_FROM_RECORD",
  "RECORD_AUTHORIZES_DECISION",
  "RECORD_INTRODUCES_DECISION",
  "SAME_AS",
  "VALIDATES",
];

// ---------------------------------------------------------------------------
// Phase 2 whitelist (live names)
//
// Mirrors the Python module's _derive_phase2_whitelist() output — a sorted
// snapshot of (spec §3 edges' live names, minus universals) ∪ extra-live.
// Do NOT re-derive here from SPEC_TO_LIVE — the Python module is canonical
// and snapshotting avoids drift if either side's spec list changes.
// ---------------------------------------------------------------------------

export const PHASE2_WHITELIST_LIVE: string[] = [
  "ABOUT_AGENDA_ITEM",
  "AMENDS_AGREEMENT",
  "AT_INSTITUTION",
  "AT_MEETING",
  "CANDIDATE_ACTOR",
  "CAST_VOTE",
  "CONTROLLED_BY",
  "CONTROLLED_BY_COMMITTEE",
  "COUNTERPARTY_ACTOR",
  "DECIDED_AT",
  "DECIDED_BY",
  "DISCLOSED_IN_FILING",
  "FILED_BY",
  "FILED_BY_COMMITTEE",
  "FILED_BY_ORG",
  "FILED_DURING_SEAT_SERVICE",
  "FILED_FOR_ELECTION",
  "FILED_FOR_SEAT",
  "FILED_WITH",
  "FOR_ELECTION",
  "FOR_SEAT",
  "FROM_SOURCE",
  "HEARD_BY",
  "HEARD_IN",
  "HELD_BY",
  "MEMBER",
  "MEMBER_OF_ORG",
  "OFFICIAL_FILER",
  "OPERATED_BY",
  "PARTY_TO",
  "PART_OF_CASE",
  "PART_OF_MEETING",
  "PRIMARY_FOR_ELECTION",
  "PRIMARY_PLACE",
  "RELATED_TO_ELECTION",
  "RELATES_TO_AGREEMENT",
  "RELATES_TO_PROGRAM",
  "RELATES_TO_PROJECT",
  "RESULT_OF_ELECTION",
  "TO_TARGET",
];

// ---------------------------------------------------------------------------
// Edge-style classification
// ---------------------------------------------------------------------------

// Sorted dedup of SPEC_TO_LIVE[FROM_SOURCE, TO_TARGET, DISCLOSED_IN, UNDER_AGREEMENT].
export const MONEY_EDGES_LIVE: string[] = [
  "DISCLOSED_IN_FILING",
  "FROM_SOURCE",
  "RELATES_TO_AGREEMENT",
  "TO_TARGET",
];

// CONSTRAINS is not yet materialized — empty list is the correct behavior.
export const LEGAL_EDGES_LIVE: string[] = [];

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Return the list of live AuraDB edge names for a spec §3 edge name.
 *
 * Returns an empty list if the spec name is unknown or has no live equivalent
 * (e.g., CONSTRAINS, which is not yet materialized in the live projection).
 */
export function specToLive(specEdge: string): string[] {
  return SPEC_TO_LIVE[specEdge] ?? [];
}
