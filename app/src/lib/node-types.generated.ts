// AUTO-GENERATED from registry/node-types.json — DO NOT EDIT BY HAND.
// Regenerate: node app/scripts/codegen-node-types.mjs
// The registry is the single source of truth for the node-type contract.

export const ALL_TYPES = [
  "Person",
  "Organization",
  "Committee",
  "Seat",
  "SeatService",
  "Election",
  "Candidacy",
  "Meeting",
  "AgendaItem",
  "Decision",
  "Filing",
  "MoneyFlow",
  "Case",
  "Proceeding",
  "Project",
  "Program",
  "Agreement",
  "Amendment",
  "Record",
  "Place",
  "Issue",
  "Membership",
] as const;

export type NodeType = (typeof ALL_TYPES)[number];

// Canonical id-prefix → NodeType, derived from registry id_prefixes. Includes
// the real `agenda-item-` prefix and the legacy aliases (actor-/inst-/eid-).
export const TYPE_BY_ID_PREFIX: Record<string, NodeType> = {
  "person-": "Person",
  "org-": "Organization",
  "committee-": "Committee",
  "seat-": "Seat",
  "seatservice-": "SeatService",
  "election-": "Election",
  "candidacy-": "Candidacy",
  "meeting-": "Meeting",
  "agenda-item-": "AgendaItem",
  "decision-": "Decision",
  "filing-": "Filing",
  "moneyflow-": "MoneyFlow",
  "case-": "Case",
  "proceeding-": "Proceeding",
  "project-": "Project",
  "program-": "Program",
  "agreement-": "Agreement",
  "amendment-": "Amendment",
  "record-": "Record",
  "place-": "Place",
  "issue-": "Issue",
  "membership-": "Membership",
  "actor-": "Person",
  "inst-": "Organization",
  "eid-": "Filing",
};

// Longest-prefix-first so a strict-prefix pair (e.g. a hypothetical `agenda-`
// vs `agenda-item-`) can never mis-resolve. Today's registry has no such pair,
// but sorting makes the resolver robust to future additions regardless of map
// key order.
const _PREFIXES_LONGEST_FIRST = Object.keys(TYPE_BY_ID_PREFIX).sort(
  (a, b) => b.length - a.length,
);

/**
 * Resolve a node's canonical NodeType from its id prefix. The single shared
 * id-prefix resolver for the app — returns null for an id with no known prefix.
 */
export function resolveTypeFromId(id: string): NodeType | null {
  for (const prefix of _PREFIXES_LONGEST_FIRST) {
    if (id.startsWith(prefix)) return TYPE_BY_ID_PREFIX[prefix];
  }
  return null;
}
