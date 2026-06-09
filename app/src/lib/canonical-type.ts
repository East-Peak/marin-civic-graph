import { ALL_TYPES, type NodeType } from "./type-display";

// Labels known to be subtypes of Organization — they should resolve to Organization.
const ORGANIZATION_SUBTYPES = new Set([
  "Government",
  "Nonprofit",
  "Business",
  "Political",
  "Court",
  "Department",
  "Commission",
]);

const TYPE_BY_ID_PREFIX: Record<string, NodeType> = {
  "person-": "Person",
  "org-": "Organization",
  "committee-": "Committee",
  "seat-": "Seat",
  "seatservice-": "SeatService",
  "election-": "Election",
  "candidacy-": "Candidacy",
  "meeting-": "Meeting",
  // Real agenda ids are `agenda-item-*` (see scripts/extract_agenda_items.py);
  // the old `agendaitem-` never matched real data. Kept in parity with
  // registry/node-types.json id_prefixes + scripts/canonical_type.py.
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
  // Legacy
  "actor-": "Person",
  "inst-": "Organization",
  "eid-": "Filing",
};

/** Resolve a node's canonical NodeType. Prefers ID prefix → known-type label → first label. */
export function canonicalType(labels: string[], id: string): NodeType | null {
  for (const [prefix, type] of Object.entries(TYPE_BY_ID_PREFIX)) {
    if (id.startsWith(prefix)) return type;
  }
  // If any label is a known base NodeType, prefer it over subtypes.
  const knownBase = labels.find((lbl) => (ALL_TYPES as readonly string[]).includes(lbl));
  if (knownBase) return knownBase as NodeType;
  // If any label is an Organization subtype, return Organization.
  if (labels.some((lbl) => ORGANIZATION_SUBTYPES.has(lbl))) return "Organization";
  return null;
}
