import "server-only";

import { canonicalType } from "@/lib/canonical-type";
import {
  LEGAL_EDGES_LIVE,
  MONEY_EDGES_LIVE,
  PHASE2_WHITELIST_LIVE,
} from "@/lib/edge-vocabulary";
import { resolveIdAlias } from "@/lib/id-aliases";
import { effectiveEventDate } from "@/lib/server/entity-temporal";
import { loadGraph } from "@/lib/server/graph-engine";
import { getSubstrateDb } from "@/lib/server/substrate";
import { urlSegmentForType, type NodeType } from "@/lib/type-display";
import type {
  EdgeStyle,
  EntityEdge,
  EntityPayload,
  IdentityLink,
  MoneyRollup,
  Neighbor,
  RecordLineageItem,
} from "@/lib/server/entity-loader";

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

const MONEY_EDGES = new Set(MONEY_EDGES_LIVE);
const LEGAL_EDGES = new Set(LEGAL_EDGES_LIVE);

const SHORT_ID_PREFIX: Record<string, string> = {
  organization: "org-",
};

function candidateIdFromSegment(typeSegment: string, slug: string): string {
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

function classifyEdgeStyle(relType: string): EdgeStyle {
  if (MONEY_EDGES.has(relType)) return "money";
  if (LEGAL_EDGES.has(relType)) return "legal-constrains";
  return "governance";
}

function canonicalTypeFromStored(type: string, id: string): NodeType | null {
  return canonicalType([type], id);
}

function rowToNeighbor(row: {
  id: string;
  type: string;
  label: string;
  ring: number;
  role: "must-show" | "phase-2";
}): Neighbor | null {
  const type = canonicalTypeFromStored(row.type, row.id);
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
    event_date: null,
  };
}

function resolveFocusId(typeSegment: string, slug: string): string | null {
  const graph = loadGraph();
  const candidateId = candidateIdFromSegment(typeSegment, slug);

  // Substrate nodes are baked through a primary-key/MERGE path, so the live
  // duplicate-id guard cannot occur here. Keep the same candidate order, but
  // each lookup is a simple id hit against the baked nodes table.
  if (graph.nodeMeta.has(candidateId)) return candidateId;

  const shortId = shortCandidateIdFromSegment(typeSegment, slug);
  if (shortId && graph.nodeMeta.has(shortId)) return shortId;

  const alias = resolveIdAlias(candidateId);
  if (alias && alias.id !== candidateId && graph.nodeMeta.has(alias.id)) {
    return alias.id;
  }

  return null;
}

function datedNeighborProps(
  neighbors: Pick<Neighbor, "id" | "type">[],
): Map<string, string | null> {
  const graph = loadGraph();
  const out = new Map<string, string | null>();

  for (const neighbor of neighbors) {
    const dateless =
      effectiveEventDate(neighbor.type, {}) === null &&
      neighbor.type !== "Meeting" &&
      neighbor.type !== "Decision" &&
      neighbor.type !== "MoneyFlow" &&
      neighbor.type !== "Filing" &&
      neighbor.type !== "Election" &&
      neighbor.type !== "Proceeding" &&
      neighbor.type !== "Agreement" &&
      neighbor.type !== "Amendment" &&
      neighbor.type !== "Case" &&
      neighbor.type !== "AgendaItem" &&
      neighbor.type !== "Record" &&
      neighbor.type !== "SeatService";
    if (dateless) continue;
    out.set(neighbor.id, effectiveEventDate(neighbor.type, graph.getNodeProps(neighbor.id)));
  }

  return out;
}

function neighborTotalOrFallback(
  focusId: string,
  focusType: NodeType,
  neighbors: Neighbor[],
): number {
  try {
    return loadGraph().neighborTotal(focusId, focusType);
  } catch (err) {
    console.warn(`[entity-loader-substrate] neighbor-total failed for focus=${focusId}:`, err);
    return neighbors.length;
  }
}

function withEventDates(neighbors: Neighbor[]): Neighbor[] {
  const dateByNeighborId = datedNeighborProps(neighbors);
  return neighbors.map((neighbor) => ({
    ...neighbor,
    event_date: dateByNeighborId.get(neighbor.id) ?? null,
  }));
}

function toEntityEdge(
  edge: {
    source?: string;
    target?: string;
    start_id?: string;
    end_id?: string;
    relationship: string;
  },
): EntityEdge {
  const source = edge.start_id ?? edge.source;
  const target = edge.end_id ?? edge.target;
  if (!source || !target) {
    throw new Error(`Missing edge endpoint for ${edge.relationship}`);
  }
  return {
    source,
    target,
    type: edge.relationship,
    style: classifyEdgeStyle(edge.relationship),
  };
}

type IdentityLinkRow = {
  source: string;
  target: string;
  assertion_id: string;
  basis: string | null;
  decided_at: string | null;
};

type MoneyRollupRow = {
  flows_in_count: number;
  money_in_total: number;
  flows_out_count: number;
  money_out_total: number;
  top_counterparties: string;
};

function peerLabel(peerId: string): string {
  return loadGraph().nodeMeta.get(peerId)?.label ?? peerId;
}

function loadIdentityLinks(focusId: string): IdentityLink[] {
  const db = getSubstrateDb();
  const rows = db
    .prepare(
      `
      SELECT source, target, assertion_id, basis, decided_at
      FROM identity_links
      WHERE source = ? OR target = ?
      `,
    )
    .all(focusId, focusId) as IdentityLinkRow[];

  return rows
    .map((row): IdentityLink => {
      const focusIsSource = row.source === focusId;
      const peerId = focusIsSource ? row.target : row.source;
      return {
        peer_id: peerId,
        peer_label: peerLabel(peerId),
        direction: focusIsSource ? "verifies" : "verified_by",
        assertion_id: row.assertion_id,
        basis: row.basis,
        decided_at: row.decided_at,
      };
    })
    .sort((a, b) => {
      if (a.direction !== b.direction) return a.direction === "verifies" ? -1 : 1;
      return a.peer_id.localeCompare(b.peer_id);
    });
}

function parseCounterparties(value: string): MoneyRollup["top_counterparties"] {
  const parsed = JSON.parse(value) as unknown;
  if (!Array.isArray(parsed)) return [];
  return parsed.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const row = item as Record<string, unknown>;
    if (typeof row.id !== "string" || typeof row.label !== "string") return [];
    const total = Number(row.total);
    if (!Number.isFinite(total)) return [];
    return [{ id: row.id, label: row.label, total }];
  });
}

function loadMoneyRollup(focusId: string): MoneyRollup | null {
  const db = getSubstrateDb();
  const row = db
    .prepare(
      `
      SELECT
        flows_in_count,
        money_in_total,
        flows_out_count,
        money_out_total,
        top_counterparties
      FROM money_rollups
      WHERE org_id = ?
      `,
    )
    .get(focusId) as MoneyRollupRow | undefined;
  if (!row) return null;
  return {
    flows_in_count: Number(row.flows_in_count),
    money_in_total: Number(row.money_in_total),
    flows_out_count: Number(row.flows_out_count),
    money_out_total: Number(row.money_out_total),
    top_counterparties: parseCounterparties(row.top_counterparties),
  };
}

function loadRecordLineage(focusId: string): RecordLineageItem[] {
  const graph = loadGraph();
  const seen = new Set<string>([focusId]);
  const queue: Array<{ id: string; depth: number }> = [{ id: focusId, depth: 0 }];
  const lineage: RecordLineageItem[] = [];

  while (queue.length > 0 && lineage.length < 10) {
    const current = queue.shift()!;
    if (current.depth >= 3) continue;

    const edges = [...(graph.adjacency.get(current.id) ?? [])]
      .filter((edge) => edge.rel === "DERIVED_FROM_RECORD")
      .sort((a, b) => a.peer.localeCompare(b.peer));

    for (const edge of edges) {
      if (lineage.length >= 10) break;
      if (seen.has(edge.peer)) continue;
      const meta = graph.nodeMeta.get(edge.peer);
      if (!meta || meta.type !== "Record") continue;
      seen.add(edge.peer);
      const depth = current.depth + 1;
      lineage.push({ id: edge.peer, label: meta.label, depth });
      queue.push({ id: edge.peer, depth });
    }
  }

  return lineage;
}

function substrateDividends(id: string, type: NodeType): Partial<EntityPayload> {
  if (type === "Organization") {
    return {
      identity_links: loadIdentityLinks(id),
      money_rollup: loadMoneyRollup(id),
    };
  }
  if (type === "Record") {
    return {
      record_lineage: loadRecordLineage(id),
    };
  }
  return {};
}

export async function loadEntitySubstrate(
  typeSegment: string,
  slug: string,
): Promise<EntityPayload | null> {
  const graph = loadGraph();
  const id = resolveFocusId(typeSegment, slug);
  if (!id) return null;

  const meta = graph.nodeMeta.get(id);
  if (!meta) return null;
  const type = canonicalTypeFromStored(meta.type, id);
  if (!type) return null;

  const properties = { ...graph.getNodeProps(id), id };
  const label = labelFromProps(id, properties);
  const focusEventDate = effectiveEventDate(type, properties);

  if (TIER1_TYPES.has(type)) {
    const mustShowRaw = graph.mustShowFor(type, id);
    const mustShowIds = mustShowRaw.map((row) => row.id);
    const mustShowNeighbors = mustShowRaw
      .map(rowToNeighbor)
      .filter((neighbor): neighbor is Neighbor => neighbor !== null);

    const phase2Raw =
      mustShowIds.length >= NODE_CAP
        ? []
        : graph.phase2Fill(id, mustShowIds, Math.max(0, NODE_CAP - mustShowIds.length));
    const phase2Neighbors = phase2Raw
      .map(rowToNeighbor)
      .filter((neighbor): neighbor is Neighbor => neighbor !== null);

    const seen = new Set<string>([id]);
    const neighbors: Neighbor[] = [];
    for (const neighbor of [...mustShowNeighbors, ...phase2Neighbors]) {
      if (seen.has(neighbor.id)) continue;
      seen.add(neighbor.id);
      neighbors.push(neighbor);
    }

    const edges = graph
      .edgesAmongSelected([id, ...neighbors.map((neighbor) => neighbor.id)], PHASE2_WHITELIST_LIVE)
      .map(toEntityEdge);

    return {
      id,
      type,
      properties,
      label,
      neighbors: withEventDates(neighbors),
      edges,
      neighbor_total: neighborTotalOrFallback(id, type, neighbors),
      focus_event_date: focusEventDate,
      ...substrateDividends(id, type),
    };
  }

  const tier2 = graph.tier2Neighborhood(id, type);
  const neighbors = tier2.neighbors
    .map(rowToNeighbor)
    .filter((neighbor): neighbor is Neighbor => neighbor !== null);
  const edges = tier2.edges.map(toEntityEdge);

  return {
    id,
    type,
    properties,
    label,
    neighbors: withEventDates(neighbors),
    edges,
    neighbor_total: neighborTotalOrFallback(id, type, neighbors),
    focus_event_date: focusEventDate,
    ...substrateDividends(id, type),
  };
}
