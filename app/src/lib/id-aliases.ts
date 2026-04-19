// app/src/lib/id-aliases.ts
import type { NodeType } from "./type-display";

// Per spec §4.2. Legacy prefixes from earlier projection stages.
const LEGACY_PREFIX_MAP: Record<string, string> = {
  "actor-": "person-",
  "inst-": "org-",
  "eid-": "filing-",
};

// Canonical id-prefix → NodeType.
const CANONICAL_PREFIX_MAP: Record<string, NodeType> = {
  "person-": "Person",
  "org-": "Organization",
  "committee-": "Committee",
  "seat-": "Seat",
  "seatservice-": "SeatService",
  "election-": "Election",
  "candidacy-": "Candidacy",
  "meeting-": "Meeting",
  "agendaitem-": "AgendaItem",
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
};

export type ResolvedId = { id: string; type: NodeType };

export function resolveIdAlias(id: string, contextType?: NodeType): ResolvedId | null {
  let canonicalId = id;
  for (const [legacy, canonical] of Object.entries(LEGACY_PREFIX_MAP)) {
    if (id.startsWith(legacy)) {
      // Only apply if context is compatible (actor- → person- only makes sense for Person).
      const resolvedType = CANONICAL_PREFIX_MAP[canonical];
      if (contextType && contextType !== resolvedType) continue;
      canonicalId = canonical + id.slice(legacy.length);
      break;
    }
  }
  for (const [prefix, type] of Object.entries(CANONICAL_PREFIX_MAP)) {
    if (canonicalId.startsWith(prefix)) {
      if (contextType && contextType !== type) return null;
      return { id: canonicalId, type };
    }
  }
  return null;
}
