// Hop-scaled per-type expand quotas + aggregate caps, per spec §6.3
// "Expand contract."
//
// The explorer's click-expand (hop=1) and right-click-expand-all (hop=2..4)
// share the same table; each step doubles (roughly) the 1-hop quota. The
// aggregate cap is the total number of new nodes a single expand can return
// across all types combined — it trims the long tail when the per-type quotas
// collectively exceed the budget.
//
// See the plan at docs/superpowers/plans/2026-04-19-open-marin-explorer-data-search-browse.md
// Task 1 for the source-of-truth table.

import type { NodeType } from "@/lib/type-display";

export type HopLimit = 1 | 2 | 3 | 4;

export type TypeQuota = {
  hop1: number;
  hop2: number;
  hop3: number;
  hop4: number;
};

// Spec §6.3 Expand contract — full table. Every NodeType has an entry so no
// caller has to special-case "unknown type → no quota."
export const EXPAND_QUOTAS: Record<NodeType, TypeQuota> = {
  MoneyFlow:   { hop1: 4, hop2: 8, hop3: 16, hop4: 24 },
  Decision:    { hop1: 4, hop2: 8, hop3: 16, hop4: 24 },
  Case:        { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Project:     { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Program:     { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Agreement:   { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Amendment:   { hop1: 1, hop2: 2, hop3: 4,  hop4: 6 },
  Filing:      { hop1: 3, hop2: 6, hop3: 12, hop4: 18 },
  Committee:   { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Election:    { hop1: 1, hop2: 2, hop3: 4,  hop4: 6 },
  Candidacy:   { hop1: 1, hop2: 2, hop3: 4,  hop4: 6 },
  Meeting:     { hop1: 3, hop2: 6, hop3: 12, hop4: 18 },
  Proceeding:  { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Person:      { hop1: 3, hop2: 6, hop3: 12, hop4: 18 },
  Organization:{ hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Seat:        { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  SeatService: { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Membership:  { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  EconomicInterest: { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  AgendaItem:  { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Record:      { hop1: 2, hop2: 4, hop3: 8,  hop4: 12 },
  Place:       { hop1: 1, hop2: 2, hop3: 4,  hop4: 6 },
  Issue:       { hop1: 1, hop2: 2, hop3: 4,  hop4: 6 },
};

// Aggregate cap per hop — the total number of new nodes any one expand call
// may return, regardless of how they split across types.
export const AGGREGATE_CAPS: Record<HopLimit, number> = {
  1: 20,
  2: 80,
  3: 160,
  4: 240,
};

/** Per-type per-hop quota. Useful in tests and for query-builder sub-LIMITs. */
export function quotaFor(type: NodeType, hop: HopLimit): number {
  const row = EXPAND_QUOTAS[type];
  switch (hop) {
    case 1: return row.hop1;
    case 2: return row.hop2;
    case 3: return row.hop3;
    case 4: return row.hop4;
  }
}

/** Aggregate cap for a hop limit. */
export function aggregateCapFor(hop: HopLimit): number {
  return AGGREGATE_CAPS[hop];
}
