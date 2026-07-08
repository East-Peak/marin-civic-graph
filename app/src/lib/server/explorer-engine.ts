import "server-only";

import {
  LEGAL_EDGES_LIVE,
  MONEY_EDGES_LIVE,
  PHASE2_WHITELIST_LIVE,
} from "@/lib/edge-vocabulary";
import { aggregateCapFor, quotaFor, type HopLimit } from "@/lib/explorer/expand-quotas";
import { loadGraph } from "@/lib/server/graph-engine";
import { SUB_SPECS, UNIVERSAL_EXPAND_EDGES } from "@/lib/server/explorer-queries";
import { urlSegmentForType, type NodeType } from "@/lib/type-display";

type EdgeStyle = "governance" | "money" | "legal-constrains";

type RankValue = string | number | null;

type RankingPart = {
  key: string;
  dir: "asc" | "desc";
};

type ExpandCandidate = {
  id: string;
  type: NodeType;
  label: string;
  ring: HopLimit;
  rankValue: RankValue;
  eventDate: string | null;
  typePriority: number;
};

export type ExpandSubstrateParams = {
  focusId: string;
  hopLimit: HopLimit;
  excludedNodeTypes: NodeType[];
  excludedEdgeTypes: string[];
  alreadyLoadedIds: string[];
  includeUniversals: boolean;
};

export type ExpandSubstrateNode = {
  id: string;
  type: NodeType;
  label: string;
  route: string;
  ring: HopLimit;
  event_date: string | null;
};

export type ExpandSubstrateEdge = {
  source: string;
  target: string;
  type: string;
  style: EdgeStyle;
};

export type ExpandSubstrateResult = {
  nodes: ExpandSubstrateNode[];
  edges: ExpandSubstrateEdge[];
  cap: number;
};

const MONEY_EDGES = new Set(MONEY_EDGES_LIVE);
const LEGAL_EDGES = new Set(LEGAL_EDGES_LIVE);
const SPECS_BY_TYPE = new Map(SUB_SPECS.map((spec) => [spec.typeLabel, spec]));
const RANKING_PARTS_BY_TYPE = new Map(
  SUB_SPECS.map((spec) => [spec.typeLabel, parseRankingKey(spec.rankingKey)]),
);

function classifyEdgeStyle(relType: string): EdgeStyle {
  if (MONEY_EDGES.has(relType)) return "money";
  if (LEGAL_EDGES.has(relType)) return "legal-constrains";
  return "governance";
}

function routeFor(id: string, type: NodeType): string {
  const slug = id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
  return `/${urlSegmentForType(type)}/${slug}`;
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values));
}

function allowedExpandRels(
  excludedEdgeTypes: string[],
  includeUniversals: boolean,
): string[] {
  const excluded = new Set(excludedEdgeTypes);
  const baseAllowed = PHASE2_WHITELIST_LIVE.filter((rel) => !excluded.has(rel));
  if (!includeUniversals) return baseAllowed;
  return unique([
    ...baseAllowed,
    ...UNIVERSAL_EXPAND_EDGES.filter((rel) => !excluded.has(rel)),
  ]);
}

function parseRankingKey(rankingKey: string): RankingPart[] {
  return rankingKey.split(",").map((rawPart) => {
    const match = rawPart.trim().match(/^c\.([A-Za-z0-9_]+)\s+(ASC|DESC)$/);
    if (!match) {
      throw new Error(`Unsupported expand ranking key: ${rankingKey}`);
    }
    return {
      key: match[1],
      dir: match[2].toLowerCase() as "asc" | "desc",
    };
  });
}

function rawValue(value: unknown): RankValue {
  if (typeof value === "number" || typeof value === "string") return value;
  return null;
}

function valueForKey(id: string, props: Record<string, unknown>, key: string): RankValue {
  if (key === "id") return id;
  return rawValue(props[key]);
}

function valueForExpr(
  id: string,
  props: Record<string, unknown>,
  expr: string,
): RankValue {
  const trimmed = expr.trim();
  if (trimmed === "null") return null;
  if (trimmed === "c.id") return id;

  const propMatch = trimmed.match(/^c\.([A-Za-z0-9_]+)$/);
  if (propMatch) return valueForKey(id, props, propMatch[1]);

  const coalesceMatch = trimmed.match(/^coalesce\((.*)\)$/);
  if (coalesceMatch) {
    for (const part of coalesceMatch[1].split(",")) {
      const value = valueForExpr(id, props, part);
      if (value != null) return value;
    }
    return null;
  }

  throw new Error(`Unsupported expand projection expression: ${expr}`);
}

function eventDateForExpr(
  id: string,
  props: Record<string, unknown>,
  expr: string,
): string | null {
  const value = valueForExpr(id, props, expr);
  return typeof value === "string" && value.length > 0 ? value : null;
}

function lexCompare(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

function compareNonNullValues(a: string | number, b: string | number): number {
  if (typeof a === "number" && typeof b === "number") {
    return a === b ? 0 : a < b ? -1 : 1;
  }
  return lexCompare(String(a), String(b));
}

function compareCypherValues(a: RankValue, b: RankValue, dir: "asc" | "desc"): number {
  if (a == null || b == null) {
    if (a == null && b == null) return 0;
    const ascending = a == null ? 1 : -1;
    return dir === "asc" ? ascending : -ascending;
  }
  const cmp = compareNonNullValues(a, b);
  return dir === "asc" ? cmp : -cmp;
}

function compareRankDescNullsLast(a: RankValue, b: RankValue): number {
  if (a == null || b == null) {
    if (a == null && b == null) return 0;
    return a == null ? 1 : -1;
  }
  return -compareNonNullValues(a, b);
}

function candidateDistances(
  focusId: string,
  hopLimit: HopLimit,
  allowedRels: string[],
): Map<string, HopLimit> {
  const graph = loadGraph();
  const allowed = new Set(allowedRels);
  const distances = new Map<string, HopLimit>();
  let frontier = new Set([focusId]);

  if (allowed.size === 0) return distances;

  for (let hop = 1; hop <= hopLimit; hop += 1) {
    const next = new Set<string>();
    for (const id of frontier) {
      for (const edge of graph.adjacency.get(id) ?? []) {
        if (!allowed.has(edge.rel)) continue;
        if (edge.peer === focusId) continue;
        if (distances.has(edge.peer)) continue;
        distances.set(edge.peer, hop as HopLimit);
        next.add(edge.peer);
      }
    }
    frontier = next;
  }

  return distances;
}

function compareWithinType(
  a: ExpandCandidate,
  b: ExpandCandidate,
  rankingParts: RankingPart[],
): number {
  if (a.ring !== b.ring) return a.ring - b.ring;

  const graph = loadGraph();
  const aProps = graph.getNodeProps(a.id);
  const bProps = graph.getNodeProps(b.id);
  for (const part of rankingParts) {
    const cmp = compareCypherValues(
      valueForKey(a.id, aProps, part.key),
      valueForKey(b.id, bProps, part.key),
      part.dir,
    );
    if (cmp !== 0) return cmp;
  }

  return lexCompare(a.id, b.id);
}

function compareOuter(a: ExpandCandidate, b: ExpandCandidate): number {
  if (a.ring !== b.ring) return a.ring - b.ring;
  if (a.typePriority !== b.typePriority) return a.typePriority - b.typePriority;
  const rankCmp = compareRankDescNullsLast(a.rankValue, b.rankValue);
  return rankCmp !== 0 ? rankCmp : lexCompare(a.id, b.id);
}

function candidatePools(
  focusId: string,
  hopLimit: HopLimit,
  excludedNodeTypes: NodeType[],
  alreadyLoadedIds: string[],
  allowedRels: string[],
): ExpandCandidate[] {
  const graph = loadGraph();
  const excludedTypes = new Set<string>(excludedNodeTypes);
  const excludedIds = new Set([focusId, ...alreadyLoadedIds]);
  const byType = new Map<NodeType, ExpandCandidate[]>();

  for (const [id, ring] of candidateDistances(focusId, hopLimit, allowedRels)) {
    if (excludedIds.has(id)) continue;
    const meta = graph.nodeMeta.get(id);
    if (!meta) continue;
    if (excludedTypes.has(meta.type)) continue;

    const spec = SPECS_BY_TYPE.get(meta.type as NodeType);
    if (!spec) continue;

    const type = meta.type as NodeType;
    const props = graph.getNodeProps(id);
    const candidates = byType.get(type) ?? [];
    candidates.push({
      id,
      type,
      label: meta.label,
      ring,
      rankValue: valueForExpr(id, props, spec.rankValueExpr),
      eventDate: eventDateForExpr(id, props, spec.eventDateExpr),
      typePriority: spec.typePriority,
    });
    byType.set(type, candidates);
  }

  const rows: ExpandCandidate[] = [];
  for (const spec of SUB_SPECS) {
    if (excludedTypes.has(spec.typeLabel)) continue;
    const candidates = [...(byType.get(spec.typeLabel) ?? [])];
    const rankingParts = RANKING_PARTS_BY_TYPE.get(spec.typeLabel) ?? [];
    candidates.sort((a, b) => compareWithinType(a, b, rankingParts));
    rows.push(...candidates.slice(0, quotaFor(spec.typeLabel, hopLimit)));
  }

  return rows;
}

export function expandSubstrate(params: ExpandSubstrateParams): ExpandSubstrateResult {
  const {
    focusId,
    hopLimit,
    excludedNodeTypes,
    excludedEdgeTypes,
    alreadyLoadedIds,
    includeUniversals,
  } = params;
  const graph = loadGraph();
  const allowedRels = allowedExpandRels(excludedEdgeTypes, includeUniversals);
  const cap = aggregateCapFor(hopLimit);
  const selected = candidatePools(
    focusId,
    hopLimit,
    excludedNodeTypes,
    alreadyLoadedIds,
    allowedRels,
  )
    .sort(compareOuter)
    .slice(0, cap);

  const nodes = selected.map((candidate) => ({
    id: candidate.id,
    type: candidate.type,
    label: candidate.label,
    route: routeFor(candidate.id, candidate.type),
    ring: candidate.ring,
    event_date: candidate.eventDate,
  }));

  const unionIds = unique([focusId, ...alreadyLoadedIds, ...selected.map((node) => node.id)]);
  const edges =
    unionIds.length >= 2
      ? graph.edgesAmongSelected(unionIds, allowedRels).map((edge) => ({
          source: edge.start_id,
          target: edge.end_id,
          type: edge.relationship,
          style: classifyEdgeStyle(edge.relationship),
        }))
      : [];

  return { nodes, edges, cap };
}
