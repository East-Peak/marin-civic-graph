// app/src/lib/type-display.ts
// Per spec §4.1 + §4.2. Do not fork — this is the single source of truth.

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
  "EconomicInterest",
] as const;

export type NodeType = (typeof ALL_TYPES)[number];

// Search corpus per §3.3 — all entity types, Record handled as secondary bucket.
export const INDEXED_TYPES: NodeType[] = [
  "Person",
  "Organization",
  "Decision",
  "Project",
  "Program",
  "Case",
  "Meeting",
  "Filing",
  "Committee",
  "Agreement",
  "Amendment",
  "Election",
  "Place",
  "Issue",
];

const DISPLAY_NAMES: Record<NodeType, string> = {
  Person: "People",
  Organization: "Organizations",
  Committee: "Committees",
  Seat: "Seats",
  SeatService: "Seat services",
  Election: "Elections",
  Candidacy: "Candidacies",
  Meeting: "Meetings",
  AgendaItem: "Agenda items",
  Decision: "Decisions",
  Filing: "Filings",
  MoneyFlow: "Money flows",
  Case: "Cases",
  Proceeding: "Proceedings",
  Project: "Projects",
  Program: "Programs",
  Agreement: "Agreements",
  Amendment: "Amendments",
  Record: "Source records",
  Place: "Places",
  Issue: "Issues",
  Membership: "Memberships",
  EconomicInterest: "Economic interests",
};

// Convert PascalCase to kebab-case for URLs.
export function urlSegmentForType(type: NodeType): string {
  return type.replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase();
}

export function displayNameForType(type: NodeType): string {
  return DISPLAY_NAMES[type];
}
