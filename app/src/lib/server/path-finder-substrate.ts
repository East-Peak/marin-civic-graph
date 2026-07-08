import "server-only";

import {
  EDGE_WEIGHTS,
  LOOSE_ONLY_EDGES,
  scorePath,
  type FindPathOptions,
  type PathResult,
} from "@/lib/server/path-finder";
import { loadGraph, type AdjacencyEntry, type GraphEngine } from "@/lib/server/graph-engine";

const DEFAULT_MAX_HOPS = 4;
const PATH_ENUMERATION_CAP = 20_000;

const EVENT_DATE_KEYS = [
  "meeting_date",
  "decided_at",
  "flow_date",
  "signed_at",
  "election_date",
  "occurred_at",
  "proceeding_date",
  "date",
  "effective_date",
  "filed_at",
  "started_at",
  "start_date",
  "parent_meeting_date",
  "published_at",
  "captured_at",
] as const;

type RawPathRow = Parameters<typeof scorePath>[0];

function allowedRels(loose: boolean): Set<string> {
  const rels = new Set(Object.keys(EDGE_WEIGHTS));
  if (loose) {
    for (const rel of LOOSE_ONLY_EDGES) rels.add(rel);
  }
  return rels;
}

function eventDateFor(graph: GraphEngine, id: string): string | null {
  const props = graph.getNodeProps(id);
  for (const key of EVENT_DATE_KEYS) {
    const value = props[key];
    if (value !== null && value !== undefined) return String(value);
  }
  return null;
}

function labelFor(graph: GraphEngine, id: string): string {
  const props = graph.getNodeProps(id);
  const searchLabel = props.search_label;
  if (searchLabel !== null && searchLabel !== undefined) return String(searchLabel);

  const metaLabel = graph.nodeMeta.get(id)?.label;
  if (metaLabel && metaLabel !== id) return metaLabel;

  const name = props.name;
  if (name !== null && name !== undefined) return String(name);
  return id;
}

function rowForPath(graph: GraphEngine, nodeIds: string[], edgeTypes: string[]): RawPathRow {
  return {
    node_ids: nodeIds,
    node_types: nodeIds.map((id) => graph.nodeMeta.get(id)?.type ?? "Unknown"),
    node_labels: nodeIds.map((id) => labelFor(graph, id)),
    node_event_dates: nodeIds.map((id) => eventDateFor(graph, id)),
    edge_types: edgeTypes,
  };
}

function orderedAllowedEdges(edges: AdjacencyEntry[], rels: Set<string>): AdjacencyEntry[] {
  return edges
    .filter((edge) => rels.has(edge.rel))
    .sort((a, b) => {
      const peerCmp = a.peer.localeCompare(b.peer);
      if (peerCmp !== 0) return peerCmp;
      const relCmp = a.rel.localeCompare(b.rel);
      if (relCmp !== 0) return relCmp;
      const startCmp = a.start.localeCompare(b.start);
      return startCmp !== 0 ? startCmp : a.end.localeCompare(b.end);
    });
}

export async function findPathSubstrate(
  fromId: string,
  toId: string,
  options: FindPathOptions = {},
): Promise<PathResult> {
  if (fromId === toId) return { found: false };

  const graph = loadGraph();
  if (!graph.nodeMeta.has(fromId) || !graph.nodeMeta.has(toId)) {
    return { found: false };
  }

  const loose = options.loose ?? false;
  const maxHops = options.maxHops ?? DEFAULT_MAX_HOPS;
  const rels = allowedRels(loose);
  if (rels.size === 0 || maxHops <= 0) return { found: false };

  let bestResult: PathResult | null = null;
  let bestWeight = Infinity;
  let pathCount = 0;
  let capped = false;

  const visit = (currentId: string, nodeIds: string[], edgeTypes: string[]): void => {
    if (capped || edgeTypes.length >= maxHops) return;

    for (const edge of orderedAllowedEdges(graph.adjacency.get(currentId) ?? [], rels)) {
      if (capped) return;
      if (nodeIds.includes(edge.peer)) continue;

      const nextNodeIds = [...nodeIds, edge.peer];
      const nextEdgeTypes = [...edgeTypes, edge.rel];

      if (edge.peer === toId) {
        pathCount += 1;
        const scored = scorePath(rowForPath(graph, nextNodeIds, nextEdgeTypes), loose);
        if (scored !== null && scored.weight < bestWeight) {
          bestWeight = scored.weight;
          bestResult = {
            found: true,
            loose_match: scored.loose_match,
            path: scored.path,
          };
        }
        if (pathCount >= PATH_ENUMERATION_CAP) {
          capped = true;
          console.warn(
            `[path-finder-substrate] path enumeration cap hit for ${fromId} -> ${toId}; scored ${pathCount} paths`,
          );
        }
        continue;
      }

      visit(edge.peer, nextNodeIds, nextEdgeTypes);
    }
  };

  visit(fromId, [fromId], []);

  return bestResult ?? { found: false };
}
