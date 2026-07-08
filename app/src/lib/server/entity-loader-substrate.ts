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
import { urlSegmentForType, type NodeType } from "@/lib/type-display";
import type {
  EdgeStyle,
  EntityEdge,
  EntityPayload,
  Neighbor,
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
  };
}
