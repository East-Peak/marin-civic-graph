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
    const edges = await runEdgesAmongSelected([id, ...neighbors.map((n) => n.id)]);

    return {
      id,
      type,
      properties: focus.properties,
      label,
      neighbors,
      edges,
      neighbor_total: neighbors.length,
    };
  }

  // Tier 2 path — simple 1-hop neighborhood.
  const { neighbors, edges } = await loadTier2Neighborhood(id, type);

  return {
    id,
    type,
    properties: focus.properties,
    label,
    neighbors,
    edges,
    neighbor_total: neighbors.length,
  };
}
