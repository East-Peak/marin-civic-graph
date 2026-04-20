// Cypher string builders for the full-screen explorer's expand and
// expand-all operations, per spec §6.3.
//
// `buildExpandQuery()` returns a UNION-ALL-of-per-type-sub-queries pattern,
// identical in shape to Plan 2's Phase-2 fill query (entity-queries.ts), but:
//
//   * Traverses `[:whitelist*1..hopLimit]` (1 hop for click-expand, N hops
//     for right-click-expand-all).
//   * Filters out already-loaded ids so re-expanding a node doesn't re-rank
//     the same neighbors.
//   * Filters out excluded edge types at the relationship-list level and
//     excluded node types by omitting their per-type sub-query entirely.
//   * Per spec §6.3 "closer candidates preferred within each type's quota",
//     every per-type ORDER BY leads with `hop_distance ASC` (length(p) min).
//
// The builder returns `{ cypher, params, cap }` — `cap` is the aggregate node
// cap (`AGGREGATE_CAPS`) for the requested hop, and the caller trims the
// union result to `cap` rows after Cypher execution. The per-type sub-queries
// apply `LIMIT quotaFor(type, hop)` inline.

import "server-only";
import neo4j from "neo4j-driver";
import { PHASE2_WHITELIST_LIVE } from "@/lib/edge-vocabulary";
import type { NodeType } from "@/lib/type-display";
import {
  aggregateCapFor,
  quotaFor,
  type HopLimit,
} from "@/lib/explorer/expand-quotas";

// ---------------------------------------------------------------------------
// Sub-query spec per type — type-priority + ranking key inherited from
// entity-queries.ts's Phase-2 fill table (§5.1.1). The explorer's per-type
// ordering per spec §6.3 prepends `hop_distance ASC` so closer-hop candidates
// win when a type's quota is contested.
// ---------------------------------------------------------------------------

type ExpandSubSpec = {
  typeLabel: NodeType;
  typePriority: number;
  /** Ranking clause (without leading `ORDER BY`) that follows hop_distance ASC. */
  rankingKey: string;
  /** Cypher expression for the rank_value projection — typically the leading prop. */
  rankValueExpr: string;
};

const SUB_SPECS: ExpandSubSpec[] = [
  { typeLabel: "MoneyFlow",    typePriority: 1,  rankingKey: "c.amount DESC, c.flow_date DESC",  rankValueExpr: "c.amount" },
  { typeLabel: "Decision",     typePriority: 2,  rankingKey: "c.decided_at DESC",                rankValueExpr: "c.decided_at" },
  { typeLabel: "Filing",       typePriority: 3,  rankingKey: "c.signed_at DESC",                 rankValueExpr: "c.signed_at" },
  { typeLabel: "Meeting",      typePriority: 4,  rankingKey: "c.meeting_date DESC",              rankValueExpr: "c.meeting_date" },
  { typeLabel: "Person",       typePriority: 5,  rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "Organization", typePriority: 6,  rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "AgendaItem",   typePriority: 7,  rankingKey: "c.item_number ASC",                rankValueExpr: "c.item_number" },
  { typeLabel: "Amendment",    typePriority: 8,  rankingKey: "c.effective_date DESC",            rankValueExpr: "c.effective_date" },
  { typeLabel: "Proceeding",   typePriority: 9,  rankingKey: "c.date DESC",                      rankValueExpr: "c.date" },
  { typeLabel: "Election",     typePriority: 10, rankingKey: "c.election_date DESC",             rankValueExpr: "c.election_date" },
  { typeLabel: "Candidacy",    typePriority: 11, rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "Case",         typePriority: 12, rankingKey: "c.filed_at DESC",                  rankValueExpr: "c.filed_at" },
  { typeLabel: "Project",      typePriority: 13, rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "Program",      typePriority: 14, rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "Agreement",    typePriority: 15, rankingKey: "c.effective_date DESC",            rankValueExpr: "c.effective_date" },
  { typeLabel: "Committee",    typePriority: 16, rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "Seat",         typePriority: 17, rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "SeatService",  typePriority: 18, rankingKey: "c.started_at DESC",                rankValueExpr: "c.started_at" },
  { typeLabel: "Record",       typePriority: 19, rankingKey: "c.captured_at DESC",               rankValueExpr: "c.captured_at" },
  { typeLabel: "Place",        typePriority: 20, rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
  { typeLabel: "Issue",        typePriority: 21, rankingKey: "c.id ASC",                         rankValueExpr: "c.id" },
];

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export type BuildExpandQueryParams = {
  focusId: string;
  hopLimit: HopLimit;
  /** Node types the user has toggled off — skip their per-type sub-queries. */
  excludedNodeTypes: NodeType[];
  /** Live relationship names the user has toggled off. */
  excludedEdgeTypes: string[];
  /** Ids already in the client's loaded set — filter out to avoid dupes. */
  alreadyLoadedIds: string[];
};

export type BuildExpandQueryResult = {
  cypher: string;
  params: Record<string, unknown>;
  /** Aggregate node cap for the hop — the caller truncates results to this. */
  cap: number;
};

export function buildExpandQuery(opts: BuildExpandQueryParams): BuildExpandQueryResult {
  const {
    focusId,
    hopLimit,
    excludedNodeTypes,
    excludedEdgeTypes,
    alreadyLoadedIds,
  } = opts;

  const excludedTypes = new Set<NodeType>(excludedNodeTypes);
  const excludedEdges = new Set(excludedEdgeTypes);

  // Relationship-type list = PHASE2_WHITELIST_LIVE minus user-excluded edges.
  const allowedEdges = PHASE2_WHITELIST_LIVE.filter((e) => !excludedEdges.has(e));
  // If every edge is excluded, fall back to a known-impossible rel name so the
  // pattern still parses but matches nothing (same trick as specEdges()).
  const relPattern = allowedEdges.length > 0
    ? allowedEdges.join("|")
    : "__NO_LIVE_EDGE__";

  // Build per-type sub-queries for every type not excluded.
  const activeSubs = SUB_SPECS.filter((s) => !excludedTypes.has(s.typeLabel));

  const subQueries = activeSubs.map((s) => buildSubQuery(s, relPattern, hopLimit));

  const cap = aggregateCapFor(hopLimit);

  // Empty case: no active types (every type excluded). Return a no-op query
  // that yields zero rows but still parses. `cap` is still meaningful for the
  // response envelope.
  if (subQueries.length === 0) {
    return {
      cypher: "RETURN null AS id, null AS labels, null AS label, null AS type, null AS ring, null AS rank_value, null AS type_priority LIMIT 0",
      params: { focus_id: focusId, already_loaded_ids: alreadyLoadedIds, cap: neo4j.int(cap) },
      cap,
    };
  }

  const body = subQueries.join("\nUNION ALL\n");

  // Global ORDER BY + LIMIT — spec §6.3 "(hop_distance ASC, type-priority
  // ASC, type-specific ranking key, id ASC)." The per-type sub-queries ORDER
  // BY their own ranking keys internally; the outer ORDER BY re-merges the
  // union by (ring, type-priority, id) so the aggregate-cap trim keeps the
  // most interesting candidates.
  const cypher = `CALL {
${body}
}
RETURN id, labels, label, type, ring, rank_value, type_priority
ORDER BY ring ASC, type_priority ASC, id ASC
LIMIT $cap
`;

  return {
    cypher,
    params: {
      focus_id: focusId,
      already_loaded_ids: alreadyLoadedIds,
      // Neo4j's LIMIT demands INTEGER; wrap via neo4j.int so the driver
      // doesn't send a FLOAT and get rejected with 22N01.
      cap: neo4j.int(cap),
    },
    cap,
  };
}

// ---------------------------------------------------------------------------
// Internal sub-query builder
// ---------------------------------------------------------------------------

function buildSubQuery(
  spec: ExpandSubSpec,
  relPattern: string,
  hopLimit: HopLimit,
): string {
  const limit = quotaFor(spec.typeLabel, hopLimit);

  // Dedup c via `WITH c, min(length(p)) AS hop_distance` — a candidate
  // reachable by multiple paths up to `hopLimit` appears once at its
  // shortest-path distance. hop_distance doubles as the ring annotation the
  // explorer uses for rendering.
  //
  // ORDER BY hop_distance ASC first (spec §6.3 "closer candidates preferred
  // within each type's quota"), then the type-specific ranking key, then
  // c.id ASC for a deterministic tie-break.
  return `
  MATCH p = (f {id: $focus_id})-[:${relPattern}*1..${hopLimit}]-(c:${spec.typeLabel})
  WHERE c.id <> $focus_id AND NOT c.id IN $already_loaded_ids
  WITH c, min(length(p)) AS hop_distance
  RETURN c.id AS id,
    labels(c) AS labels,
    coalesce(c.search_label, c.name, c.id) AS label,
    '${spec.typeLabel}' AS type,
    hop_distance AS ring,
    ${spec.rankValueExpr} AS rank_value,
    ${spec.typePriority} AS type_priority
  ORDER BY hop_distance ASC, ${spec.rankingKey}, c.id ASC
  LIMIT ${limit}`;
}
