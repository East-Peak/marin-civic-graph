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
] as const;

export type NodeType = (typeof ALL_TYPES)[number];
