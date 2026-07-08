import "server-only";

import {
  PHASE2_WHITELIST_LIVE,
  UNIVERSAL_EDGES_LIVE,
  specToLive,
} from "@/lib/edge-vocabulary";
import { getSubstrateDb } from "@/lib/server/substrate";
import type { NodeType } from "@/lib/type-display";

export type EdgeClass = "phase2" | "universal" | "same_as";

export type GraphNodeMeta = {
  type: string;
  label: string;
};

export type AdjacencyEntry = {
  peer: string;
  rel: string;
  out: boolean;
  edgeClass: EdgeClass;
  start: string;
  end: string;
};

export type MustShowGraphRow = {
  id: string;
  type: string;
  label: string;
  ring: 1 | 2 | 3;
  role: "must-show";
  relationship: string;
};

export type Phase2GraphRow = {
  id: string;
  type: string;
  label: string;
  ring: 1 | 2;
  role: "phase-2";
  rank_value: string | number | null;
  type_priority: number;
};

export type Tier2GraphNeighbor = {
  id: string;
  type: string;
  label: string;
  ring: 1;
  role: "must-show";
  relationship: string;
};

export type Tier2GraphEdge = {
  relationship: string;
  start_id: string;
  end_id: string;
};

export type SelectedGraphEdge = Tier2GraphEdge & {
  source: string;
  target: string;
};

export type GraphEngine = {
  nodeMeta: Map<string, GraphNodeMeta>;
  adjacency: Map<string, AdjacencyEntry[]>;
  getNodeProps(id: string): Record<string, unknown>;
  mustShowFor(focusType: NodeType, focusId: string): MustShowGraphRow[];
  phase2Fill(focusId: string, mustShowIds: string[], cap: number): Phase2GraphRow[];
  tier2Neighborhood(
    focusId: string,
    focusType: NodeType,
  ): { neighbors: Tier2GraphNeighbor[]; edges: Tier2GraphEdge[] };
  edgesAmongSelected(ids: string[], allowedRels: string[]): SelectedGraphEdge[];
  neighborTotal(focusId: string, focusType: NodeType): number;
};

type StoredNodeRow = {
  id: string;
  type: string;
  search_label: string | null;
};

type StoredEdgeRow = {
  source: string;
  rel: string;
  target: string;
};

type Direction = "out" | "in" | "any";

type MustShowHop = {
  rels: string[];
  dir: Direction;
  endTypeFilter?: string[];
};

type MustShowPattern = {
  hops: MustShowHop[];
  ring: 1 | 2 | 3;
  relationshipTag: string;
};

type Phase2Quota = {
  type: string;
  typePriority: number;
  limit: number;
  rankValue(candidate: Candidate, graph: GraphData): string | number | null;
  compare(a: Candidate, b: Candidate, graph: GraphData): number;
};

type Candidate = {
  id: string;
  ring: 1 | 2;
};

type GraphData = {
  nodeMeta: Map<string, GraphNodeMeta>;
  adjacency: Map<string, AdjacencyEntry[]>;
  getNodeProps(id: string): Record<string, unknown>;
};

const PHASE2_RELS = new Set(PHASE2_WHITELIST_LIVE);
const UNIVERSAL_RELS = new Set(UNIVERSAL_EDGES_LIVE);
const SAME_AS_REL = "SAME_AS";
const ADJACENCY_RELS = Array.from(
  new Set([...PHASE2_WHITELIST_LIVE, ...UNIVERSAL_EDGES_LIVE, SAME_AS_REL]),
);
const PROPS_CACHE_LIMIT = 256;

function unique(values: string[]): string[] {
  return Array.from(new Set(values));
}

function specEdges(...names: string[]): string[] {
  return unique(names.flatMap((name) => specToLive(name)));
}

const MUST_SHOW_PATTERNS: Record<string, MustShowPattern[]> = {
  Person: [
    {
      hops: [{ rels: specEdges("HELD_BY"), dir: "in", endTypeFilter: ["SeatService"] }],
      ring: 1,
      relationshipTag: "HELD_BY",
    },
    {
      hops: [
        { rels: specEdges("HELD_BY"), dir: "in", endTypeFilter: ["SeatService"] },
        { rels: specEdges("FOR_SEAT"), dir: "out", endTypeFilter: ["Seat"] },
      ],
      ring: 2,
      relationshipTag: "FOR_SEAT",
    },
    {
      hops: [{ rels: specEdges("CONTROLLED_BY"), dir: "in", endTypeFilter: ["Committee"] }],
      ring: 1,
      relationshipTag: "CONTROLLED_BY",
    },
    {
      hops: [{ rels: specEdges("BY_PERSON"), dir: "in", endTypeFilter: ["Candidacy"] }],
      ring: 1,
      relationshipTag: "BY_PERSON",
    },
    {
      hops: [{ rels: specEdges("PARTY_TO"), dir: "any", endTypeFilter: ["Case"] }],
      ring: 1,
      relationshipTag: "PARTY_TO",
    },
    {
      hops: [
        { rels: specEdges("HELD_BY"), dir: "in", endTypeFilter: ["SeatService"] },
        { rels: specEdges("FOR_SEAT"), dir: "out", endTypeFilter: ["Seat"] },
        {
          rels: specEdges("AT_INSTITUTION"),
          dir: "out",
          endTypeFilter: ["Organization", "Government"],
        },
      ],
      ring: 3,
      relationshipTag: "AT_INSTITUTION",
    },
  ],
  Decision: [
    {
      hops: [{ rels: specEdges("AT_MEETING"), dir: "out", endTypeFilter: ["Meeting"] }],
      ring: 1,
      relationshipTag: "AT_MEETING",
    },
    {
      hops: [{ rels: specEdges("ABOUT_ITEM"), dir: "out", endTypeFilter: ["AgendaItem"] }],
      ring: 1,
      relationshipTag: "ABOUT_AGENDA_ITEM",
    },
    {
      hops: [
        {
          rels: specEdges("DECIDED_BY"),
          dir: "out",
          endTypeFilter: ["Organization", "Government"],
        },
      ],
      ring: 1,
      relationshipTag: "DECIDED_BY",
    },
    {
      hops: [{ rels: specEdges("CAST_VOTE"), dir: "in", endTypeFilter: ["Person"] }],
      ring: 1,
      relationshipTag: "CAST_VOTE",
    },
    {
      hops: [{ rels: specEdges("ABOUT_PROJECT"), dir: "out", endTypeFilter: ["Project"] }],
      ring: 1,
      relationshipTag: "ABOUT_PROJECT",
    },
    {
      hops: [{ rels: specEdges("ABOUT_PROGRAM"), dir: "out", endTypeFilter: ["Program"] }],
      ring: 1,
      relationshipTag: "ABOUT_PROGRAM",
    },
    {
      hops: [{ rels: specEdges("CONSTRAINS"), dir: "in", endTypeFilter: ["Case"] }],
      ring: 1,
      relationshipTag: "CONSTRAINS",
    },
  ],
  Project: [
    {
      hops: [{ rels: specEdges("FOR_PROJECT"), dir: "in", endTypeFilter: ["Agreement"] }],
      ring: 1,
      relationshipTag: "FOR_PROJECT",
    },
    {
      hops: [
        { rels: specEdges("FOR_PROJECT"), dir: "in", endTypeFilter: ["Agreement"] },
        { rels: specEdges("AMENDS"), dir: "in", endTypeFilter: ["Amendment"] },
      ],
      ring: 2,
      relationshipTag: "AMENDS",
    },
    {
      hops: [{ rels: specEdges("ABOUT_PROJECT"), dir: "in", endTypeFilter: ["Decision"] }],
      ring: 1,
      relationshipTag: "ABOUT_PROJECT",
    },
    {
      hops: [
        { rels: specEdges("ABOUT_PROJECT"), dir: "in", endTypeFilter: ["Decision"] },
        { rels: specEdges("ABOUT_PROGRAM"), dir: "out", endTypeFilter: ["Program"] },
      ],
      ring: 2,
      relationshipTag: "ABOUT_PROGRAM",
    },
  ],
  Program: [
    {
      hops: [{ rels: specEdges("ABOUT_PROGRAM"), dir: "in", endTypeFilter: ["Decision"] }],
      ring: 1,
      relationshipTag: "ABOUT_PROGRAM",
    },
    {
      hops: [
        { rels: specEdges("ABOUT_PROGRAM"), dir: "in", endTypeFilter: ["Decision"] },
        { rels: specEdges("ABOUT_PROJECT"), dir: "out", endTypeFilter: ["Project"] },
      ],
      ring: 2,
      relationshipTag: "ABOUT_PROJECT",
    },
    {
      hops: [
        { rels: specEdges("ABOUT_PROGRAM"), dir: "in", endTypeFilter: ["Decision"] },
        { rels: specEdges("CONSTRAINS"), dir: "in", endTypeFilter: ["Case"] },
      ],
      ring: 2,
      relationshipTag: "CONSTRAINS",
    },
  ],
  Case: [
    {
      hops: [{ rels: specEdges("PART_OF"), dir: "in", endTypeFilter: ["Proceeding"] }],
      ring: 1,
      relationshipTag: "PART_OF_CASE",
    },
    {
      hops: [
        {
          rels: specEdges("HEARD_IN"),
          dir: "out",
          endTypeFilter: ["Organization", "Court"],
        },
      ],
      ring: 1,
      relationshipTag: "HEARD_IN",
    },
    {
      hops: [
        {
          rels: specEdges("PARTY_TO"),
          dir: "in",
          endTypeFilter: ["Person", "Organization"],
        },
      ],
      ring: 1,
      relationshipTag: "PARTY_TO",
    },
    {
      hops: [{ rels: specEdges("CONSTRAINS"), dir: "out", endTypeFilter: ["Decision"] }],
      ring: 1,
      relationshipTag: "CONSTRAINS",
    },
  ],
  Meeting: [
    {
      hops: [
        {
          rels: specEdges("AT_INSTITUTION"),
          dir: "out",
          endTypeFilter: ["Organization", "Government"],
        },
      ],
      ring: 1,
      relationshipTag: "AT_INSTITUTION",
    },
    {
      hops: [{ rels: specEdges("PART_OF"), dir: "in", endTypeFilter: ["AgendaItem"] }],
      ring: 1,
      relationshipTag: "PART_OF_MEETING",
    },
    {
      hops: [{ rels: specEdges("AT_MEETING"), dir: "in", endTypeFilter: ["Decision"] }],
      ring: 1,
      relationshipTag: "AT_MEETING",
    },
  ],
  Filing: [
    {
      hops: [
        {
          rels: specEdges("FILED_BY"),
          dir: "out",
          endTypeFilter: ["Person", "Committee", "Organization"],
        },
      ],
      ring: 1,
      relationshipTag: "FILED_BY",
    },
    {
      hops: [{ rels: specEdges("FOR_ELECTION"), dir: "out", endTypeFilter: ["Election"] }],
      ring: 1,
      relationshipTag: "FOR_ELECTION",
    },
    {
      hops: [{ rels: specEdges("DISCLOSED_IN"), dir: "in", endTypeFilter: ["MoneyFlow"] }],
      ring: 1,
      relationshipTag: "DISCLOSED_IN_FILING",
    },
  ],
  Committee: [
    {
      hops: [{ rels: specEdges("CONTROLLED_BY"), dir: "out", endTypeFilter: ["Person"] }],
      ring: 1,
      relationshipTag: "CONTROLLED_BY",
    },
    {
      hops: [{ rels: specEdges("FILED_BY"), dir: "in", endTypeFilter: ["Filing"] }],
      ring: 1,
      relationshipTag: "FILED_BY",
    },
  ],
};

function rawValue(props: Record<string, unknown>, key: string): string | number | null {
  const value = props[key];
  if (typeof value === "number" || typeof value === "string") return value;
  return null;
}

function edgeCountToMustShow(candidateId: string, mustShowIds: Set<string>, graph: GraphData): number {
  const seen = new Set<string>();
  for (const edge of graph.adjacency.get(candidateId) ?? []) {
    if (!mustShowIds.has(edge.peer)) continue;
    seen.add(`${edge.rel}\u0000${edge.start}\u0000${edge.end}`);
  }
  return seen.size;
}

function compareValues(
  a: string | number | null,
  b: string | number | null,
  dir: "asc" | "desc",
): number {
  if (a == null || b == null) {
    if (a == null && b == null) return 0;
    // Cypher treats null as a largest value for ORDER BY.
    return dir === "asc" ? (a == null ? 1 : -1) : a == null ? -1 : 1;
  }
  let cmp: number;
  if (typeof a === "number" && typeof b === "number") {
    cmp = a === b ? 0 : a < b ? -1 : 1;
  } else {
    cmp = lexCompare(String(a), String(b));
  }
  return dir === "asc" ? cmp : -cmp;
}

function lexCompare(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

function compareId(a: Candidate, b: Candidate): number {
  return lexCompare(a.id, b.id);
}

function byProp(
  key: string,
  dir: "asc" | "desc",
): (a: Candidate, b: Candidate, graph: GraphData) => number {
  return (a, b, graph) =>
    compareValues(
      rawValue(graph.getNodeProps(a.id), key),
      rawValue(graph.getNodeProps(b.id), key),
      dir,
    );
}

function byEdgesToMustShow(
  a: Candidate,
  b: Candidate,
  graph: GraphData,
  mustShowIds: Set<string>,
): number {
  return compareValues(
    edgeCountToMustShow(a.id, mustShowIds, graph),
    edgeCountToMustShow(b.id, mustShowIds, graph),
    "desc",
  );
}

function chainComparators(
  ...comparators: Array<(a: Candidate, b: Candidate, graph: GraphData) => number>
): (a: Candidate, b: Candidate, graph: GraphData) => number {
  return (a, b, graph) => {
    for (const comparator of comparators) {
      const cmp = comparator(a, b, graph);
      if (cmp !== 0) return cmp;
    }
    return 0;
  };
}

function phase2Quotas(mustShowIds: Set<string>): Phase2Quota[] {
  return [
    {
      type: "MoneyFlow",
      typePriority: 1,
      limit: 8,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "amount"),
      compare: chainComparators(byProp("amount", "desc"), byProp("flow_date", "desc"), compareId),
    },
    {
      type: "Decision",
      typePriority: 2,
      limit: 8,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "decided_at"),
      compare: chainComparators(byProp("decided_at", "desc"), compareId),
    },
    {
      type: "Filing",
      typePriority: 3,
      limit: 6,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "signed_at"),
      compare: chainComparators(byProp("signed_at", "desc"), compareId),
    },
    {
      type: "Meeting",
      typePriority: 4,
      limit: 6,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "meeting_date"),
      compare: chainComparators(byProp("meeting_date", "desc"), compareId),
    },
    {
      type: "Person",
      typePriority: 5,
      limit: 6,
      rankValue: (candidate, graph) => edgeCountToMustShow(candidate.id, mustShowIds, graph),
      compare: chainComparators(
        (a, b, graph) => byEdgesToMustShow(a, b, graph, mustShowIds),
        compareId,
      ),
    },
    {
      type: "Organization",
      typePriority: 6,
      limit: 4,
      rankValue: (candidate, graph) => edgeCountToMustShow(candidate.id, mustShowIds, graph),
      compare: chainComparators(
        (a, b, graph) => byEdgesToMustShow(a, b, graph, mustShowIds),
        compareId,
      ),
    },
    {
      type: "AgendaItem",
      typePriority: 7,
      limit: 4,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "item_number"),
      compare: chainComparators(byProp("item_number", "asc"), compareId),
    },
    {
      type: "Amendment",
      typePriority: 8,
      limit: 2,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "effective_date"),
      compare: chainComparators(byProp("effective_date", "desc"), compareId),
    },
    {
      type: "Proceeding",
      typePriority: 9,
      limit: 4,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "date"),
      compare: chainComparators(byProp("date", "desc"), compareId),
    },
    {
      type: "Election",
      typePriority: 10,
      limit: 2,
      rankValue: (candidate, graph) => rawValue(graph.getNodeProps(candidate.id), "election_date"),
      compare: chainComparators(byProp("election_date", "desc"), compareId),
    },
    {
      type: "Candidacy",
      typePriority: 11,
      limit: 2,
      rankValue: (candidate) => candidate.id,
      compare: compareId,
    },
  ];
}

function edgeClassFor(rel: string): EdgeClass | null {
  if (rel === SAME_AS_REL) return "same_as";
  if (PHASE2_RELS.has(rel)) return "phase2";
  if (UNIVERSAL_RELS.has(rel)) return "universal";
  return null;
}

function pushAdjacency(
  adjacency: Map<string, AdjacencyEntry[]>,
  source: string,
  target: string,
  rel: string,
  edgeClass: EdgeClass,
) {
  const sourceEntries = adjacency.get(source) ?? [];
  sourceEntries.push({ peer: target, rel, out: true, edgeClass, start: source, end: target });
  adjacency.set(source, sourceEntries);

  const targetEntries = adjacency.get(target) ?? [];
  targetEntries.push({ peer: source, rel, out: false, edgeClass, start: source, end: target });
  adjacency.set(target, targetEntries);
}

function matchesDirection(edge: AdjacencyEntry, dir: Direction): boolean {
  if (dir === "any") return true;
  if (dir === "out") return edge.out;
  return !edge.out;
}

function matchesType(
  nodeMeta: Map<string, GraphNodeMeta>,
  id: string,
  filter: string[] | undefined,
): boolean {
  if (!filter) return true;
  const meta = nodeMeta.get(id);
  return meta ? filter.includes(meta.type) : false;
}

function traversePattern(
  focusId: string,
  pattern: MustShowPattern,
  graph: GraphData,
): string[] {
  let frontier = new Set([focusId]);

  for (const hop of pattern.hops) {
    if (hop.rels.length === 0) return [];
    const rels = new Set(hop.rels);
    const next = new Set<string>();
    for (const id of frontier) {
      for (const edge of graph.adjacency.get(id) ?? []) {
        if (!rels.has(edge.rel)) continue;
        if (!matchesDirection(edge, hop.dir)) continue;
        if (!matchesType(graph.nodeMeta, edge.peer, hop.endTypeFilter)) continue;
        next.add(edge.peer);
      }
    }
    frontier = next;
  }

  frontier.delete(focusId);
  return Array.from(frontier);
}

function toMustShowRow(
  id: string,
  pattern: MustShowPattern,
  nodeMeta: Map<string, GraphNodeMeta>,
): MustShowGraphRow | null {
  const meta = nodeMeta.get(id);
  if (!meta) return null;
  return {
    id,
    type: meta.type,
    label: meta.label,
    ring: pattern.ring,
    role: "must-show",
    relationship: pattern.relationshipTag,
  };
}

function whitelistDistances(
  focusId: string,
  graph: GraphData,
  maxHops: 1 | 2,
): Map<string, 1 | 2> {
  const distances = new Map<string, 1 | 2>();
  let frontier = new Set([focusId]);

  for (let hop = 1; hop <= maxHops; hop += 1) {
    const next = new Set<string>();
    for (const id of frontier) {
      for (const edge of graph.adjacency.get(id) ?? []) {
        if (!PHASE2_RELS.has(edge.rel)) continue;
        if (edge.peer === focusId) continue;
        if (!distances.has(edge.peer)) {
          distances.set(edge.peer, hop as 1 | 2);
          next.add(edge.peer);
        }
      }
    }
    frontier = next;
  }

  return distances;
}

function phase2Fill(
  focusId: string,
  mustShowIds: string[],
  cap: number,
  graph: GraphData,
): Phase2GraphRow[] {
  if (cap <= 0) return [];
  const excluded = new Set([focusId, ...mustShowIds]);
  const mustShowSet = new Set(mustShowIds);
  const candidatesByType = new Map<string, Candidate[]>();

  for (const [id, ring] of whitelistDistances(focusId, graph, 2)) {
    if (excluded.has(id)) continue;
    const meta = graph.nodeMeta.get(id);
    if (!meta) continue;
    const candidates = candidatesByType.get(meta.type) ?? [];
    candidates.push({ id, ring });
    candidatesByType.set(meta.type, candidates);
  }

  const rows: Phase2GraphRow[] = [];
  for (const quota of phase2Quotas(mustShowSet)) {
    const candidates = [...(candidatesByType.get(quota.type) ?? [])];
    candidates.sort((a, b) => quota.compare(a, b, graph));
    for (const candidate of candidates.slice(0, quota.limit)) {
      const meta = graph.nodeMeta.get(candidate.id);
      if (!meta) continue;
      rows.push({
        id: candidate.id,
        type: meta.type,
        label: meta.label,
        ring: candidate.ring,
        role: "phase-2",
        rank_value: quota.rankValue(candidate, graph),
        type_priority: quota.typePriority,
      });
    }
  }

  return rows.slice(0, cap);
}

function isAllowedTier2Edge(
  focusType: NodeType,
  edge: AdjacencyEntry,
  peerMeta: GraphNodeMeta,
): boolean {
  if (focusType === "Record") {
    return edge.rel === "EVIDENCED_BY" && !edge.out;
  }
  if (focusType === "Place") {
    return peerMeta.type !== "Issue" && (edge.rel === "IN_JURISDICTION" || PHASE2_RELS.has(edge.rel));
  }
  if (focusType === "Issue") {
    return peerMeta.type !== "Place" && (edge.rel === "RELATES_TO_ISSUE" || PHASE2_RELS.has(edge.rel));
  }
  return peerMeta.type !== "Place" && peerMeta.type !== "Issue" && PHASE2_RELS.has(edge.rel);
}

function compareByTypeThenId(
  a: { id: string; type: string },
  b: { id: string; type: string },
): number {
  const typeCmp = lexCompare(a.type, b.type);
  return typeCmp !== 0 ? typeCmp : lexCompare(a.id, b.id);
}

function tier2Neighborhood(
  focusId: string,
  focusType: NodeType,
  graph: GraphData,
): { neighbors: Tier2GraphNeighbor[]; edges: Tier2GraphEdge[] } {
  const matches: Array<{ edge: AdjacencyEntry; peerMeta: GraphNodeMeta }> = [];
  for (const edge of graph.adjacency.get(focusId) ?? []) {
    if (edge.peer === focusId) continue;
    const peerMeta = graph.nodeMeta.get(edge.peer);
    if (!peerMeta) continue;
    if (!isAllowedTier2Edge(focusType, edge, peerMeta)) continue;
    matches.push({ edge, peerMeta });
  }

  matches.sort((a, b) => {
    const peerCmp = compareByTypeThenId(
      { id: a.edge.peer, type: a.peerMeta.type },
      { id: b.edge.peer, type: b.peerMeta.type },
    );
    if (peerCmp !== 0) return peerCmp;
    const relCmp = lexCompare(a.edge.rel, b.edge.rel);
    if (relCmp !== 0) return relCmp;
    const startCmp = lexCompare(a.edge.start, b.edge.start);
    return startCmp !== 0 ? startCmp : lexCompare(a.edge.end, b.edge.end);
  });

  const selectedIds = new Set<string>();
  const neighbors: Tier2GraphNeighbor[] = [];
  for (const match of matches) {
    if (selectedIds.has(match.edge.peer)) continue;
    if (neighbors.length >= 40) break;
    selectedIds.add(match.edge.peer);
    neighbors.push({
      id: match.edge.peer,
      type: match.peerMeta.type,
      label: match.peerMeta.label,
      ring: 1,
      role: "must-show",
      relationship: match.edge.rel,
    });
  }

  const seenEdges = new Set<string>();
  const edges: Tier2GraphEdge[] = [];
  for (const match of matches) {
    if (!selectedIds.has(match.edge.peer)) continue;
    const key = `${match.edge.rel}\u0000${match.edge.start}\u0000${match.edge.end}`;
    if (seenEdges.has(key)) continue;
    seenEdges.add(key);
    edges.push({
      relationship: match.edge.rel,
      start_id: match.edge.start,
      end_id: match.edge.end,
    });
  }

  return { neighbors, edges };
}

function edgesAmongSelected(
  ids: string[],
  allowedRels: string[],
  graph: GraphData,
): SelectedGraphEdge[] {
  const selected = new Set(ids);
  const allowed = new Set(allowedRels);
  const seen = new Set<string>();
  const rows: SelectedGraphEdge[] = [];

  for (const id of selected) {
    for (const edge of graph.adjacency.get(id) ?? []) {
      if (!edge.out) continue;
      if (!allowed.has(edge.rel)) continue;
      if (!selected.has(edge.start) || !selected.has(edge.end)) continue;
      if (edge.start === edge.end) continue;
      const source = edge.start < edge.end ? edge.start : edge.end;
      const target = edge.start < edge.end ? edge.end : edge.start;
      const key = `${edge.rel}\u0000${edge.start}\u0000${edge.end}`;
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({
        source,
        target,
        relationship: edge.rel,
        start_id: edge.start,
        end_id: edge.end,
      });
    }
  }

  rows.sort((a, b) => {
    const relCmp = lexCompare(a.relationship, b.relationship);
    if (relCmp !== 0) return relCmp;
    const startCmp = lexCompare(a.start_id, b.start_id);
    return startCmp !== 0 ? startCmp : lexCompare(a.end_id, b.end_id);
  });
  return rows;
}

function neighborTotal(focusId: string, focusType: NodeType, graph: GraphData): number {
  if (focusType === "Record") {
    return new Set(
      (graph.adjacency.get(focusId) ?? [])
        .filter((edge) => edge.rel === "EVIDENCED_BY" && !edge.out)
        .map((edge) => edge.peer)
        .filter((id) => graph.nodeMeta.has(id)),
    ).size;
  }

  if (focusType === "Place" || focusType === "Issue") {
    const total = new Set<string>();
    for (const edge of graph.adjacency.get(focusId) ?? []) {
      const meta = graph.nodeMeta.get(edge.peer);
      if (!meta) continue;
      const placeAllowed =
        focusType === "Place" &&
        meta.type !== "Issue" &&
        (edge.rel === "IN_JURISDICTION" || PHASE2_RELS.has(edge.rel));
      const issueAllowed =
        focusType === "Issue" &&
        meta.type !== "Place" &&
        (edge.rel === "RELATES_TO_ISSUE" || PHASE2_RELS.has(edge.rel));
      if (placeAllowed || issueAllowed) total.add(edge.peer);
    }
    total.delete(focusId);
    return total.size;
  }

  let total = 0;
  for (const [id] of whitelistDistances(focusId, graph, 2)) {
    const meta = graph.nodeMeta.get(id);
    if (!meta) continue;
    if (meta.type === "Place" || meta.type === "Issue") continue;
    total += 1;
  }
  return total;
}

function createGraphEngine(): GraphEngine {
  const db = getSubstrateDb();
  const nodeMeta = new Map<string, GraphNodeMeta>();
  const adjacency = new Map<string, AdjacencyEntry[]>();
  const propsCache = new Map<string, Record<string, unknown>>();

  const nodeRows = db
    .prepare("SELECT id, type, search_label FROM nodes")
    .all() as StoredNodeRow[];
  for (const row of nodeRows) {
    nodeMeta.set(row.id, { type: row.type, label: row.search_label ?? row.id });
  }

  const placeholders = ADJACENCY_RELS.map(() => "?").join(", ");
  const edgeRows = db
    .prepare(`SELECT source, rel, target FROM edges WHERE rel IN (${placeholders})`)
    .all(...ADJACENCY_RELS) as StoredEdgeRow[];
  for (const row of edgeRows) {
    const edgeClass = edgeClassFor(row.rel);
    if (!edgeClass) continue;
    pushAdjacency(adjacency, row.source, row.target, row.rel, edgeClass);
  }

  const propsStmt = db.prepare("SELECT props FROM nodes WHERE id = ?");
  const graph: GraphData = {
    nodeMeta,
    adjacency,
    getNodeProps(id: string) {
      const cached = propsCache.get(id);
      if (cached) return cached;

      const row = propsStmt.get(id) as { props: string } | undefined;
      const props = row ? (JSON.parse(row.props) as Record<string, unknown>) : {};
      propsCache.set(id, props);
      if (propsCache.size > PROPS_CACHE_LIMIT) {
        const firstKey = propsCache.keys().next().value as string | undefined;
        if (firstKey) propsCache.delete(firstKey);
      }
      return props;
    },
  };

  return {
    nodeMeta,
    adjacency,
    getNodeProps: graph.getNodeProps,
    mustShowFor(focusType: NodeType, focusId: string) {
      const patterns = MUST_SHOW_PATTERNS[focusType];
      if (!patterns) throw new Error(`Unsupported Tier 1 focus type: ${focusType}`);
      const rows: MustShowGraphRow[] = [];
      for (const pattern of patterns) {
        for (const id of traversePattern(focusId, pattern, graph)) {
          const row = toMustShowRow(id, pattern, nodeMeta);
          if (row) rows.push(row);
        }
      }
      return rows;
    },
    phase2Fill(focusId: string, mustShowIds: string[], cap: number) {
      return phase2Fill(focusId, mustShowIds, cap, graph);
    },
    tier2Neighborhood(focusId: string, focusType: NodeType) {
      return tier2Neighborhood(focusId, focusType, graph);
    },
    edgesAmongSelected(ids: string[], allowedRels: string[]) {
      return edgesAmongSelected(ids, allowedRels, graph);
    },
    neighborTotal(focusId: string, focusType: NodeType) {
      return neighborTotal(focusId, focusType, graph);
    },
  };
}

let graphSingleton: GraphEngine | null = null;

export function loadGraph(): GraphEngine {
  if (graphSingleton) return graphSingleton;
  graphSingleton = createGraphEngine();
  return graphSingleton;
}
