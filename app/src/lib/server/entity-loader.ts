// Entity-page data loader — resolves a (typeSegment, slug) URL into an
// EntityPayload (focus node + 1–2 hop neighborhood + intra-neighborhood edges)
// per spec §5.1.1 and §6.2.
//
// Shape:
//   /{type-url}/{slug}  →  canonical id  →  focus node  →  neighborhood
//
// Tier 1 focus types (Person, Decision, Project, Program, Case, Meeting,
// Filing, Committee) run Query 1 (must-show) + Query 2 (Phase-2 fill) plus a
// third query for intra-neighborhood edges.
//
// Tier 2 focus types run a single 1-hop whitelist neighborhood query capped
// at 40 nodes.

import "server-only";
import { runQuery } from "@/lib/neo4j";
import { canonicalType } from "@/lib/canonical-type";
import { resolveIdAlias } from "@/lib/id-aliases";
import {
  MONEY_EDGES_LIVE,
  LEGAL_EDGES_LIVE,
  PHASE2_WHITELIST_LIVE,
} from "@/lib/edge-vocabulary";
import {
  buildMustShowQuery,
  buildPhase2FillQuery,
  buildEdgesAmongSelectedQuery,
  buildTier2NeighborhoodQuery,
} from "@/lib/server/entity-queries";
import { effectiveEventDate } from "@/lib/server/entity-temporal";
import { urlSegmentForType, type NodeType } from "@/lib/type-display";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type NeighborRole = "must-show" | "phase-2";

export type Neighbor = {
  id: string;
  type: NodeType;
  label: string;
  route: string; // /{type-url}/{slug}
  ring: 1 | 2 | 3;
  role: NeighborRole;
  /**
   * ISO date (or date-time) for the neighbor's effective event, per
   * entity-temporal.ts / spec §5.4. `null` for durable types (Person,
   * Organization, …) and for any neighbor that lacks a dated property.
   * The TimelineRibbon consumes this — never an id-regex fallback.
   */
  event_date: string | null;
};

export type EdgeStyle = "governance" | "money" | "legal-constrains";

export type EntityEdge = {
  source: string;
  target: string;
  type: string;
  style: EdgeStyle;
};

export type EntityPayload = {
  id: string;
  type: NodeType;
  properties: Record<string, unknown>;
  label: string;
  neighbors: Neighbor[];
  edges: EntityEdge[];
  /** Total 2-hop neighborhood size for the overflow footer (§5.1.1). */
  neighbor_total: number;
  /**
   * Effective event date for the focus entity (per §5.4). Anchors the
   * timeline ribbon when the focus itself is a dated event (Meeting,
   * Decision, Filing, …). Null for durable types (Person, Project, …).
   */
  focus_event_date: string | null;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TIER1_TYPES: ReadonlySet<NodeType> = new Set<NodeType>([
  "Person",
  "Decision",
  "Project",
  "Program",
  "Case",
  "Meeting",
  "Filing",
  "Committee",
]);

const NODE_CAP = 40;
const PHASE2_TIMEOUT_MS = 500;
const NEIGHBOR_TOTAL_TIMEOUT_MS = 500;

// Money/legal sets for edge-style classification (mirrors Python
// scripts/build_signature_subgraphs.py classify_edge_style).
const MONEY_EDGES = new Set(MONEY_EDGES_LIVE);
const LEGAL_EDGES = new Set(LEGAL_EDGES_LIVE);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function classifyEdgeStyle(relType: string): EdgeStyle {
  if (MONEY_EDGES.has(relType)) return "money";
  if (LEGAL_EDGES.has(relType)) return "legal-constrains";
  return "governance";
}

/**
 * Reconstruct the candidate canonical id from a type-url segment + slug.
 *
 * The URL type segment is `urlSegmentForType(nodeType)`'s output (kebab-case),
 * and the id prefix is the lowercased PascalCase (no dash). So `seat-service`
 * → id prefix `seatservice-`. For legacy/aliased types (actor/inst/eid),
 * `resolveIdAlias` handles the remap.
 *
 * A few id prefixes diverge from the URL segment by historical choice (e.g.
 * `organization` → `org-`, `moneyflow` → `moneyflow-` does match). We keep an
 * explicit short-prefix map for the known divergences so URL lookups succeed
 * without a DB round-trip per variant.
 */
const SHORT_ID_PREFIX: Record<string, string> = {
  organization: "org-",
};

function candidateIdFromSegment(typeSegment: string, slug: string): string {
  // Collapse dashes in the type segment: "seat-service" → "seatservice".
  const prefix = typeSegment.replace(/-/g, "") + "-";
  return `${prefix}${slug}`;
}

function shortCandidateIdFromSegment(
  typeSegment: string,
  slug: string,
): string | null {
  const shortPrefix = SHORT_ID_PREFIX[typeSegment];
  return shortPrefix ? `${shortPrefix}${slug}` : null;
}

function labelFromProps(id: string, props: Record<string, unknown>): string {
  return (
    (props.search_label as string | undefined) ??
    (props.name as string | undefined) ??
    id
  );
}

function routeFor(id: string, type: NodeType): string {
  const slug = id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
  return `/${urlSegmentForType(type)}/${slug}`;
}

function toNumber(v: unknown): number {
  if (v == null) return 0;
  if (typeof v === "object" && v !== null && "toNumber" in v) {
    return (v as { toNumber(): number }).toNumber();
  }
  return Number(v);
}

// ---------------------------------------------------------------------------
// Neo4j record extraction
// ---------------------------------------------------------------------------

type Neo4jRecordLike = {
  get(key: string): unknown;
};

type Neo4jNodeLike = {
  properties: Record<string, unknown>;
  labels: string[];
};

function isNode(v: unknown): v is Neo4jNodeLike {
  return (
    typeof v === "object" &&
    v !== null &&
    "properties" in v &&
    "labels" in v
  );
}

// ---------------------------------------------------------------------------
// Focus lookup
// ---------------------------------------------------------------------------

async function fetchFocusById(id: string): Promise<Neo4jNodeLike | null> {
  // Fetch up to 2 matches so we can detect duplicate ids. Per spec §4.2,
  // collisions are treated as ingestion bugs — the frontend does not
  // disambiguate; it logs an error and returns null (→ 404).
  const records = (await runQuery(`MATCH (n {id: $id}) RETURN n LIMIT 2`, {
    id,
  })) as unknown as Neo4jRecordLike[];
  if (records.length > 1) {
    console.error(
      `[entity-loader] Duplicate id in graph: ${id} (${records.length}+ matches). Returning 404.`,
    );
    return null;
  }
  if (records.length === 0) return null;
  const node = records[0].get("n");
  if (!isNode(node)) return null;
  return node;
}

async function resolveFocus(
  typeSegment: string,
  slug: string,
): Promise<Neo4jNodeLike | null> {
  const candidateId = candidateIdFromSegment(typeSegment, slug);

  // Try the canonical id first.
  const direct = await fetchFocusById(candidateId);
  if (direct) return direct;

  // Try the short-form id prefix for types where URL segment and id prefix
  // diverge (e.g. `organization` → `org-`).
  const shortId = shortCandidateIdFromSegment(typeSegment, slug);
  if (shortId) {
    const shortHit = await fetchFocusById(shortId);
    if (shortHit) return shortHit;
  }

  // Try alias resolution (legacy prefixes: actor/inst/eid).
  const alias = resolveIdAlias(candidateId);
  if (alias && alias.id !== candidateId) {
    const aliased = await fetchFocusById(alias.id);
    if (aliased) return aliased;
  }

  return null;
}

// ---------------------------------------------------------------------------
// Must-show + Phase-2 + edges (Tier 1)
// ---------------------------------------------------------------------------

type NeighborRowRaw = {
  id: string;
  labels: string[];
  label: string;
  ring: number;
  role: NeighborRole;
};

function rowToNeighbor(row: NeighborRowRaw): Neighbor | null {
  const type = canonicalType(row.labels, row.id);
  if (!type) return null;
  const ring = ((): 1 | 2 | 3 => {
    if (row.ring === 1 || row.ring === 2 || row.ring === 3) return row.ring;
    return 1;
  })();
  return {
    id: row.id,
    type,
    label: row.label ?? row.id,
    route: routeFor(row.id, type),
    ring,
    role: row.role,
    // Date is populated in a second pass (fetchNeighborEventDates); leave
    // null here so the loader never emits a Neighbor without the field.
    event_date: null,
  };
}

async function runMustShow(
  focusType: NodeType,
  focusId: string,
): Promise<NeighborRowRaw[]> {
  const cypher = buildMustShowQuery(focusType);
  const records = (await runQuery(cypher, {
    focus_id: focusId,
  })) as unknown as Neo4jRecordLike[];
  return records.map((r) => ({
    id: String(r.get("id")),
    labels: (r.get("labels") as string[]) ?? [],
    label: String(r.get("label") ?? r.get("id")),
    ring: toNumber(r.get("ring")),
    role: "must-show" as const,
  }));
}

/**
 * Is this error a transaction-timeout / transaction-terminated error from
 * Neo4j? We can't import the driver's Neo4jError type in a server-only
 * loader without tight coupling, so we duck-type on `code`. Covers the two
 * distinct codes Neo4j emits when a TransactionConfig.timeout fires.
 */
function isTransactionTimeoutError(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const code = (err as { code?: unknown }).code;
  if (typeof code !== "string") return false;
  return (
    code === "Neo.ClientError.Transaction.TransactionTimedOut" ||
    code === "Neo.TransientError.Transaction.TransactionTerminated" ||
    code === "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration"
  );
}

async function runPhase2WithTimeout(
  focusType: NodeType,
  focusId: string,
  mustShowIds: string[],
): Promise<NeighborRowRaw[]> {
  // 500ms circuit-breaker per §5.1.1. Implemented as a real server-side
  // transaction timeout (Neo4j driver's TransactionConfig.timeout) so:
  //   - the in-flight query is actually cancelled on the server;
  //   - there's no orphan timer holding the event loop after the query returns.
  // On timeout we log a warning and fall back to must-show only.
  const cypher = buildPhase2FillQuery(focusType);
  try {
    const records = (await runQuery(
      cypher,
      { focus_id: focusId, must_show_ids: mustShowIds },
      { timeoutMs: PHASE2_TIMEOUT_MS },
    )) as unknown as Neo4jRecordLike[];
    return records.map(
      (r): NeighborRowRaw => ({
        id: String(r.get("id")),
        labels: (r.get("labels") as string[]) ?? [],
        label: String(r.get("label") ?? r.get("id")),
        ring: toNumber(r.get("ring")),
        role: "phase-2" as const,
      }),
    );
  } catch (err) {
    if (isTransactionTimeoutError(err)) {
      console.warn(
        `[entity-loader] Phase-2 query exceeded ${PHASE2_TIMEOUT_MS}ms for focus=${focusId}; falling back to must-show only`,
      );
      return [];
    }
    throw err;
  }
}

/**
 * Fetch the date-bearing properties for the given neighbor ids, and project
 * each id to its effectiveEventDate (per §5.4 / entity-temporal.ts). Returns
 * a map of id → ISO date string (or null for durable/dateless types).
 *
 * This feeds the TimelineRibbon directly — it replaces the old id-regex
 * fabrication that would mis-date neighbors with incidental date-shaped
 * substrings in their ids.
 */
async function fetchNeighborEventDates(
  neighbors: Pick<Neighbor, "id" | "type">[],
): Promise<Map<string, string | null>> {
  const out = new Map<string, string | null>();
  if (neighbors.length === 0) return out;

  // Only query for neighbors whose type can carry an event date — the
  // durable-type branch in effectiveEventDate returns null unconditionally.
  const datedNeighbors = neighbors.filter((n) => {
    // Cheap pre-filter: if the type's entry in entity-temporal would return
    // null regardless of props, skip the DB fetch.
    const dateless = effectiveEventDate(n.type, {}) === null && n.type !== "Meeting" &&
      n.type !== "Decision" && n.type !== "MoneyFlow" && n.type !== "Filing" &&
      n.type !== "Election" && n.type !== "Proceeding" && n.type !== "Agreement" &&
      n.type !== "Amendment" && n.type !== "Case" && n.type !== "AgendaItem" &&
      n.type !== "Record" && n.type !== "SeatService";
    return !dateless;
  });
  if (datedNeighbors.length === 0) {
    // All durable — the caller doesn't need to run a query.
    return out;
  }

  const ids = datedNeighbors.map((n) => n.id);
  // Pull every property that effectiveEventDate may consult, across all
  // dated types.
  const cypher = `
    MATCH (n) WHERE n.id IN $ids
    RETURN n.id AS id,
      n.meeting_date AS meeting_date,
      n.decided_at AS decided_at,
      n.flow_date AS flow_date,
      n.signed_at AS signed_at,
      n.election_date AS election_date,
      n.proceeding_date AS proceeding_date,
      n.date AS date,
      n.effective_date AS effective_date,
      n.filed_at AS filed_at,
      n.parent_meeting_date AS parent_meeting_date,
      n.published_at AS published_at,
      n.captured_at AS captured_at,
      n.started_at AS started_at,
      n.start_date AS start_date
  `;
  const records = ((await runQuery(cypher, { ids })) ?? []) as unknown as Neo4jRecordLike[];
  const propsById = new Map<string, Record<string, unknown>>();
  for (const r of records) {
    const id = String(r.get("id"));
    propsById.set(id, {
      meeting_date: r.get("meeting_date") ?? undefined,
      decided_at: r.get("decided_at") ?? undefined,
      flow_date: r.get("flow_date") ?? undefined,
      signed_at: r.get("signed_at") ?? undefined,
      election_date: r.get("election_date") ?? undefined,
      proceeding_date: r.get("proceeding_date") ?? undefined,
      date: r.get("date") ?? undefined,
      effective_date: r.get("effective_date") ?? undefined,
      filed_at: r.get("filed_at") ?? undefined,
      parent_meeting_date: r.get("parent_meeting_date") ?? undefined,
      published_at: r.get("published_at") ?? undefined,
      captured_at: r.get("captured_at") ?? undefined,
      started_at: r.get("started_at") ?? undefined,
      start_date: r.get("start_date") ?? undefined,
    });
  }
  for (const n of datedNeighbors) {
    const props = propsById.get(n.id) ?? {};
    out.set(n.id, effectiveEventDate(n.type, props));
  }
  return out;
}

/**
 * Count the true whitelist-reachable neighborhood size. This is what the
 * overflow footer (§5.1.1) announces — "if you opened the explorer at this
 * focus, N nodes would fit the same rules."
 *
 * The rules differ by focus type: Record/Place/Issue pages each waive a
 * specific universal edge (EVIDENCED_BY / IN_JURISDICTION / RELATES_TO_ISSUE)
 * to keep those focus pages from being dead-ends. The count query must
 * follow the same rules the neighborhood-loader used.
 *
 * On timeout or error, return null so callers can fall back to the local
 * neighbor count.
 */
async function runNeighborTotal(focusId: string, focusType: NodeType): Promise<number | null> {
  const whitelist = PHASE2_WHITELIST_LIVE.join("|");

  let cypher: string;
  if (focusType === "Record") {
    // Record focus: neighbors are the entities this Record provides evidence
    // for, via inverse EVIDENCED_BY.
    cypher = `
MATCH (f {id: $focus_id})<-[:EVIDENCED_BY]-(n)
WHERE n.id <> $focus_id
RETURN count(DISTINCT n) AS total
`;
  } else if (focusType === "Place") {
    cypher = `
MATCH (f {id: $focus_id})-[:IN_JURISDICTION|${whitelist}]-(n)
WHERE n.id <> $focus_id AND NOT n:Issue
RETURN count(DISTINCT n) AS total
`;
  } else if (focusType === "Issue") {
    cypher = `
MATCH (f {id: $focus_id})-[:RELATES_TO_ISSUE|${whitelist}]-(n)
WHERE n.id <> $focus_id AND NOT n:Place
RETURN count(DISTINCT n) AS total
`;
  } else {
    // Tier 1 focus types and all other Tier 2 types: whitelist-only, exclude
    // Place and Issue (§5.1.1 hero rules).
    cypher = `
MATCH (f {id: $focus_id})-[:${whitelist}*1..2]-(n)
WHERE n.id <> $focus_id AND NOT n:Place AND NOT n:Issue
RETURN count(DISTINCT n) AS total
`;
  }

  try {
    const records = (await runQuery(
      cypher,
      { focus_id: focusId },
      { timeoutMs: NEIGHBOR_TOTAL_TIMEOUT_MS },
    )) as unknown as Neo4jRecordLike[];
    if (records.length === 0) return null;
    return toNumber(records[0].get("total"));
  } catch (err) {
    if (isTransactionTimeoutError(err)) {
      console.warn(
        `[entity-loader] neighbor-total query exceeded ${NEIGHBOR_TOTAL_TIMEOUT_MS}ms for focus=${focusId}; footer will use the displayed count`,
      );
      return null;
    }
    console.warn(`[entity-loader] neighbor-total query failed for focus=${focusId}:`, err);
    return null;
  }
}

async function runEdgesAmongSelected(
  ids: string[],
): Promise<EntityEdge[]> {
  if (ids.length < 2) return [];
  const cypher = buildEdgesAmongSelectedQuery();
  const records = (await runQuery(cypher, {
    ids,
    whitelist: PHASE2_WHITELIST_LIVE,
  })) as unknown as Neo4jRecordLike[];
  return records.map((r): EntityEdge => {
    const relType = String(r.get("rel_type"));
    return {
      source: String(r.get("start_id") ?? r.get("source")),
      target: String(r.get("end_id") ?? r.get("target")),
      type: relType,
      style: classifyEdgeStyle(relType),
    };
  });
}

// ---------------------------------------------------------------------------
// Tier 2 — single 1-hop neighborhood
// ---------------------------------------------------------------------------

async function loadTier2Neighborhood(
  focusId: string,
  focusType: NodeType,
): Promise<{ neighbors: Neighbor[]; edges: EntityEdge[] }> {
  const cypher = buildTier2NeighborhoodQuery(focusType);
  const records = (await runQuery(cypher, {
    focus_id: focusId,
  })) as unknown as Neo4jRecordLike[];

  const neighbors: Neighbor[] = [];
  const edges: EntityEdge[] = [];
  for (const r of records) {
    const id = String(r.get("id"));
    const labels = (r.get("labels") as string[]) ?? [];
    const label = String(r.get("label") ?? id);
    const type = canonicalType(labels, id);
    if (!type) continue;
    neighbors.push({
      id,
      type,
      label,
      route: routeFor(id, type),
      ring: 1,
      role: "must-show",
      event_date: null, // populated by fetchNeighborEventDates in loadEntity
    });
    const relType = String(r.get("relationship"));
    const startId = String(r.get("start_id"));
    const endId = String(r.get("end_id"));
    edges.push({
      source: startId,
      target: endId,
      type: relType,
      style: classifyEdgeStyle(relType),
    });
  }
  return { neighbors, edges };
}

// ---------------------------------------------------------------------------
// Public loader
// ---------------------------------------------------------------------------

export async function loadEntity(
  typeSegment: string,
  slug: string,
): Promise<EntityPayload | null> {
  const focus = await resolveFocus(typeSegment, slug);
  if (!focus) return null;

  const id = String(focus.properties.id);
  const type = canonicalType(focus.labels, id);
  if (!type) return null;

  const label = labelFromProps(id, focus.properties);

  if (TIER1_TYPES.has(type)) {
    // Query 1 — must-show.
    const mustShowRaw = await runMustShow(type, id);
    const mustShowIds = mustShowRaw.map((r) => r.id);
    const mustShowNeighbors = mustShowRaw
      .map(rowToNeighbor)
      .filter((n): n is Neighbor => n !== null);

    // Query 2 — Phase-2 fill (wrapped in 500ms circuit breaker).
    // Skip if must-show is already ≥ 40 (per §5.1.1, cap is relaxed but Phase-2
    // is not run in that case).
    const phase2Raw =
      mustShowIds.length >= NODE_CAP
        ? []
        : await runPhase2WithTimeout(type, id, mustShowIds);
    // Trim phase-2 to the remaining cap.
    const phase2Trimmed = phase2Raw.slice(0, Math.max(0, NODE_CAP - mustShowIds.length));
    const phase2Neighbors = phase2Trimmed
      .map(rowToNeighbor)
      .filter((n): n is Neighbor => n !== null);

    // Dedupe by id (must-show takes precedence; Phase-2 query already filters
    // must_show_ids, but be defensive).
    const seen = new Set<string>([id]);
    const neighbors: Neighbor[] = [];
    for (const n of [...mustShowNeighbors, ...phase2Neighbors]) {
      if (seen.has(n.id)) continue;
      seen.add(n.id);
      neighbors.push(n);
    }

    // Query 3 — edges among all selected nodes (focus + neighbors).
    // Query 4 — true 2-hop neighborhood size for the overflow footer.
    // Query 5 — event dates for each dated neighbor (feeds the timeline
    // ribbon; no more id-regex fabrication per Codex round 1 fix 6).
    // All three run in parallel.
    const [edges, totalCount, dateByNeighborId] = await Promise.all([
      runEdgesAmongSelected([id, ...neighbors.map((n) => n.id)]),
      runNeighborTotal(id, type),
      fetchNeighborEventDates(neighbors),
    ]);
    const neighborsWithDates = neighbors.map((n) => ({
      ...n,
      event_date: dateByNeighborId.get(n.id) ?? null,
    }));
    const focusEventDate = effectiveEventDate(type, focus.properties);

    return {
      id,
      type,
      properties: focus.properties,
      label,
      neighbors: neighborsWithDates,
      edges,
      neighbor_total: totalCount ?? neighbors.length,
      focus_event_date: focusEventDate,
    };
  }

  // Tier 2 path — simple 1-hop neighborhood.
  const { neighbors, edges } = await loadTier2Neighborhood(id, type);
  const [totalCount, dateByNeighborId] = await Promise.all([
    runNeighborTotal(id, type),
    fetchNeighborEventDates(neighbors),
  ]);
  const neighborsWithDates = neighbors.map((n) => ({
    ...n,
    event_date: dateByNeighborId.get(n.id) ?? null,
  }));
  const focusEventDate = effectiveEventDate(type, focus.properties);

  return {
    id,
    type,
    properties: focus.properties,
    label,
    neighbors: neighborsWithDates,
    edges,
    neighbor_total: totalCount ?? neighbors.length,
    focus_event_date: focusEventDate,
  };
}
