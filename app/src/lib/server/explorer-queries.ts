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
// Sub-query spec per type — §6.3 Tier-2 priority table. Lower `typePriority`
// ranks earlier, so when the aggregate cap bites, low-priority types drop
// first. Each row also carries an internal ORDER BY clause — the ranking key
// that runs after `hop_distance ASC` within a single type's sub-query.
//
// `rankValueExpr` is the Cypher expression projected into `rank_value`,
// preserved through the outer UNION so the final ORDER BY can fall back on
// it for intra-type tie-breaks when the aggregate cap trims the tail.
// ---------------------------------------------------------------------------

type ExpandSubSpec = {
  typeLabel: NodeType;
  typePriority: number;
  /** Ranking clause (without leading `ORDER BY`) that follows hop_distance ASC. */
  rankingKey: string;
  /** Cypher expression for the rank_value projection — typically the leading prop. */
  rankValueExpr: string;
  /**
   * Cypher expression for the per-candidate event_date projection (mirror of
   * lib/server/entity-temporal.ts effectiveEventDate). Returns null for
   * durable types; the explorer time slider treats null as always-visible.
   * Used by /api/expand to ship an event_date column the client can plumb
   * into the Cytoscape node's data and the earliest-event time-range floor
   * (§5.4).
   */
  eventDateExpr: string;
};

// §6.3 Tier-2 priority table. NOTE on live-property drift:
//   * Proceeding uses `occurred_at` (live), NOT `proceeding_date` (spec).
//   * SeatService uses `started_at` (live), NOT `start_date` (spec).
//   * AgendaItem's ranking is "parent Meeting.meeting_date DESC, item_number
//     ASC, id ASC" per spec; here we approximate by ranking on `item_number`
//     (the parent date is unknown at sub-query level without an extra join)
//     and let the outer union ORDER BY fall back to id for determinism.
// Exported for the node-type parity test (EXHAUSTIVE_GROUPING) — exactly one
// expand sub-spec per NodeType.
export const SUB_SPECS: ExpandSubSpec[] = [
  { typeLabel: "MoneyFlow",    typePriority: 1,  rankingKey: "c.amount DESC, c.flow_date DESC", rankValueExpr: "c.amount",         eventDateExpr: "c.flow_date" },
  { typeLabel: "Decision",     typePriority: 2,  rankingKey: "c.decided_at DESC",                rankValueExpr: "c.decided_at",     eventDateExpr: "c.decided_at" },
  { typeLabel: "Case",         typePriority: 3,  rankingKey: "c.filed_at DESC",                  rankValueExpr: "c.filed_at",       eventDateExpr: "c.filed_at" },
  { typeLabel: "Project",      typePriority: 4,  rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  { typeLabel: "Program",      typePriority: 4,  rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  { typeLabel: "Agreement",    typePriority: 5,  rankingKey: "c.effective_date DESC",            rankValueExpr: "c.effective_date", eventDateExpr: "c.effective_date" },
  { typeLabel: "Amendment",    typePriority: 5,  rankingKey: "c.effective_date DESC",            rankValueExpr: "c.effective_date", eventDateExpr: "c.effective_date" },
  { typeLabel: "Filing",       typePriority: 6,  rankingKey: "c.signed_at DESC",                 rankValueExpr: "c.signed_at",      eventDateExpr: "c.signed_at" },
  { typeLabel: "Committee",    typePriority: 7,  rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  { typeLabel: "Election",     typePriority: 7,  rankingKey: "c.election_date DESC",             rankValueExpr: "c.election_date",  eventDateExpr: "c.election_date" },
  { typeLabel: "Candidacy",    typePriority: 8,  rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  { typeLabel: "Meeting",      typePriority: 8,  rankingKey: "c.meeting_date DESC",              rankValueExpr: "c.meeting_date",   eventDateExpr: "c.meeting_date" },
  // Proceeding: live graph uses `occurred_at`. entity-temporal also reads
  // `proceeding_date` as a legacy fallback; coalesce both here so either
  // shape projects cleanly.
  { typeLabel: "Proceeding",   typePriority: 9,  rankingKey: "c.occurred_at DESC",               rankValueExpr: "c.occurred_at",    eventDateExpr: "coalesce(c.occurred_at, c.proceeding_date)" },
  { typeLabel: "Person",       typePriority: 9,  rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  { typeLabel: "Organization", typePriority: 10, rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  { typeLabel: "Seat",         typePriority: 11, rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  // SeatService: live uses `started_at`. Fallback to `start_date` for
  // forward-compat with the entity-temporal reader.
  { typeLabel: "SeatService",  typePriority: 11, rankingKey: "c.started_at DESC",                rankValueExpr: "c.started_at",     eventDateExpr: "coalesce(c.started_at, c.start_date)" },
  // Membership (COI spec §4.1): person↔org affiliation, started_at-anchored
  // like its structural analog SeatService.
  { typeLabel: "Membership",   typePriority: 11, rankingKey: "c.started_at DESC",                rankValueExpr: "c.started_at",     eventDateExpr: "c.started_at" },
  { typeLabel: "AgendaItem",   typePriority: 12, rankingKey: "c.item_number ASC",                rankValueExpr: "c.item_number",    eventDateExpr: "coalesce(c.parent_meeting_date, c.meeting_date)" },
  { typeLabel: "Record",       typePriority: 13, rankingKey: "c.published_at DESC, c.captured_at DESC", rankValueExpr: "c.published_at", eventDateExpr: "coalesce(c.published_at, c.captured_at)" },
  { typeLabel: "Place",        typePriority: 14, rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
  { typeLabel: "Issue",        typePriority: 14, rankingKey: "c.id ASC",                         rankValueExpr: "c.id",             eventDateExpr: "null" },
];

// Universal edges the explorer optionally layers on top of PHASE2_WHITELIST_LIVE
// when the user enables the "universal" edge-filter class (or the focus type's
// auto-enable waiver kicks in — see explorer-state.autoEnableFiltersForFocus).
export const UNIVERSAL_EXPAND_EDGES: string[] = [
  "EVIDENCED_BY",
  "IN_JURISDICTION",
  "RELATES_TO_ISSUE",
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
  /**
   * When true, the three universal edges (EVIDENCED_BY, IN_JURISDICTION,
   * RELATES_TO_ISSUE) are added to the traversal relationship list in
   * addition to PHASE2_WHITELIST_LIVE. Defaults to false — universals are
   * structural and too noisy for routine expands.
   */
  includeUniversals?: boolean;
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
    includeUniversals = false,
  } = opts;

  const excludedTypes = new Set<NodeType>(excludedNodeTypes);
  const excludedEdges = new Set(excludedEdgeTypes);

  // Base relationship-type list: PHASE2_WHITELIST_LIVE minus user-excluded.
  // Optionally layer the three universals on top when `includeUniversals`.
  const baseAllowed = PHASE2_WHITELIST_LIVE.filter((e) => !excludedEdges.has(e));
  const allowedEdges = includeUniversals
    ? Array.from(new Set([...baseAllowed, ...UNIVERSAL_EXPAND_EDGES.filter((e) => !excludedEdges.has(e))]))
    : baseAllowed;
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
      cypher: "RETURN null AS id, null AS labels, null AS label, null AS type, null AS ring, null AS rank_value, null AS type_priority, null AS event_date LIMIT 0",
      params: { focus_id: focusId, already_loaded_ids: alreadyLoadedIds, cap: neo4j.int(cap) },
      cap,
    };
  }

  const body = subQueries.join("\nUNION ALL\n");

  // Global ORDER BY + LIMIT — spec §6.3 "(hop_distance ASC, type-priority
  // ASC, type-specific ranking key, id ASC)." The per-type sub-queries ORDER
  // BY their own ranking keys internally; the outer ORDER BY re-merges the
  // union by (ring, type_priority, rank_value DESC, id) so the aggregate-cap
  // trim keeps the highest-ranked candidates per type.
  const cypher = `CALL {
${body}
}
RETURN id, labels, label, type, ring, rank_value, type_priority, event_date
ORDER BY ring ASC, type_priority ASC, rank_value DESC, id ASC
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
    ${spec.typePriority} AS type_priority,
    ${spec.eventDateExpr} AS event_date
  ORDER BY hop_distance ASC, ${spec.rankingKey}, c.id ASC
  LIMIT ${limit}`;
}
