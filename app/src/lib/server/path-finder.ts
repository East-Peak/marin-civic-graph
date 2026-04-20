// Weighted shortest-path finder between two entities, per spec §5.6.
//
// The spec defines a per-edge weight table and a set of excluded intermediate
// node types (Record, Issue, Place, AgendaItem) that may only appear as path
// endpoints. APOC's `apoc.algo.dijkstra` takes a single weight property on the
// relationship — but our edges don't carry a `cost` property. Rather than
// materialize costs into the graph (an ingestion concern) we:
//
//   1. Enumerate all simple paths up to `maxHops` with `apoc.algo.allSimplePaths`,
//      restricted to the spec-allowed relationship types.
//   2. Reject paths that traverse an excluded intermediate node type (unless
//      `loose` is on, in which case such hops count as weight 10).
//   3. Compute total weight = Σ (per-edge weight) and return the minimum.
//
// `apoc.algo.allSimplePaths` returns paths with a bounded `maxHops` length, so
// the search space is small even on well-connected subgraphs.
//
// The "loose" toggle:
//   - Admits excluded intermediate types (Record/Issue/Place/AgendaItem) as
//     non-endpoint hops, at weight 10 per hop.
//   - Admits universal edges (EVIDENCED_BY / IN_JURISDICTION / RELATES_TO_ISSUE)
//     at weight 10 per traversal.
//   - `loose_match: true` on the result so the UI can tag "PATH VIA LOOSE MATCH."
//
// Related: Plan 3 Task 2 design notes + spec §5.6 edge weight table.

import "server-only";
import { runQuery } from "@/lib/neo4j";
import { specToLive } from "@/lib/edge-vocabulary";

// ---------------------------------------------------------------------------
// Weight table — spec §5.6
// ---------------------------------------------------------------------------

/**
 * Build the live-edge → weight map by expanding each spec-§3 edge name via
 * specToLive(). Spec names without a live mapping (e.g., CONSTRAINS, not yet
 * materialized) contribute nothing — the lookup simply returns an empty list.
 */
export const EDGE_WEIGHTS: Record<string, number> = (() => {
  const map: Record<string, number> = {};
  const add = (weight: number, specNames: string[]) => {
    for (const specName of specNames) {
      for (const live of specToLive(specName)) {
        map[live] = weight;
      }
    }
  };

  // Weight 1 — highest signal.
  add(1, ["CONSTRAINS", "CAST_VOTE", "DECIDED_BY", "PARTY_TO"]);
  // Weight 2 — money + amendments.
  add(2, ["FROM_SOURCE", "TO_TARGET", "DISCLOSED_IN", "UNDER_AGREEMENT", "AMENDS"]);
  // Weight 3 — governance structure.
  add(3, ["HELD_BY", "FOR_SEAT", "RESULT_OF", "CONTROLLED_BY", "BY_PERSON", "IN_ELECTION", "FOR_ELECTION", "FOR_PROJECT"]);
  // Weight 4.
  add(4, ["ABOUT_PROJECT", "ABOUT_PROGRAM", "ABOUT_ITEM", "BETWEEN", "HEARD_IN", "AT_INSTITUTION"]);
  // Weight 5.
  add(5, ["AT_MEETING", "FILED_BY", "PART_OF"]);

  return map;
})();

/** Universals — excluded from default pathfinding, weight 10 under loose. */
export const LOOSE_ONLY_EDGES: ReadonlySet<string> = new Set([
  "EVIDENCED_BY",
  "IN_JURISDICTION",
  "RELATES_TO_ISSUE",
]);

/** Node types that may only appear as path endpoints under default rules. */
export const EXCLUDED_INTERMEDIATE_TYPES: ReadonlySet<string> = new Set([
  "Record",
  "Issue",
  "Place",
  "AgendaItem",
]);

const LOOSE_WEIGHT = 10;
const DEFAULT_MAX_HOPS = 6;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type PathNode = {
  id: string;
  type: string;
  label: string;
};

export type PathEdge = {
  source: string;
  target: string;
  type: string;
  weight: number;
};

export type PathResult =
  | {
      found: true;
      loose_match: boolean;
      path: { nodes: PathNode[]; edges: PathEdge[]; weight: number };
    }
  | { found: false };

export type FindPathOptions = {
  loose?: boolean;
  maxHops?: number;
};

// ---------------------------------------------------------------------------
// findPath
// ---------------------------------------------------------------------------

type RawPathRow = {
  node_ids: string[];
  node_types: string[];
  node_labels: string[];
  edge_types: string[];
};

export async function findPath(
  fromId: string,
  toId: string,
  options: FindPathOptions = {},
): Promise<PathResult> {
  if (fromId === toId) {
    // A "path" to yourself isn't meaningful for the investigation UI, and
    // apoc.algo.allSimplePaths won't emit a zero-length path anyway. Treat
    // as not-found so the caller shows the "no path" hint.
    return { found: false };
  }

  const loose = options.loose ?? false;
  const maxHops = options.maxHops ?? DEFAULT_MAX_HOPS;

  // Allowed relationship types — always the weight-table edges; add the
  // universal / loose-only edges when loose is on.
  const allowedEdges: string[] = Object.keys(EDGE_WEIGHTS);
  if (loose) {
    for (const e of LOOSE_ONLY_EDGES) allowedEdges.push(e);
  }

  if (allowedEdges.length === 0) {
    // No known live edges in the weight table (shouldn't happen in practice —
    // the weight table contains at minimum CAST_VOTE, DECIDED_BY, etc.).
    return { found: false };
  }

  const relFilter = allowedEdges.join("|");

  // Project the path into plain arrays so this module doesn't depend on the
  // neo4j-driver's Path/Segment shape. The driver returns primitives per
  // `Neo4jRecord.get(...)` which are trivial to JSON-serialize.
  const cypher = `
    MATCH (from {id: $fromId}), (to {id: $toId})
    CALL apoc.algo.allSimplePaths(from, to, $relFilter, $maxHops) YIELD path
    WITH path,
         [n IN nodes(path) | n.id] AS node_ids,
         [n IN nodes(path) | labels(n)[0]] AS node_types,
         [n IN nodes(path) | coalesce(n.search_label, n.name, n.id)] AS node_labels,
         [r IN relationships(path) | type(r)] AS edge_types
    RETURN node_ids, node_types, node_labels, edge_types
    ORDER BY size(node_ids) ASC
    LIMIT 200
  `;

  const records = await runQuery(cypher, { fromId, toId, relFilter, maxHops });

  if (records.length === 0) return { found: false };

  let bestResult: PathResult | null = null;
  let bestWeight = Infinity;

  for (const record of records) {
    const row: RawPathRow = {
      node_ids: record.get("node_ids") as string[],
      node_types: record.get("node_types") as string[],
      node_labels: record.get("node_labels") as string[],
      edge_types: record.get("edge_types") as string[],
    };

    const scored = scorePath(row, loose);
    if (scored === null) continue;
    if (scored.weight < bestWeight) {
      bestWeight = scored.weight;
      bestResult = {
        found: true,
        loose_match: scored.loose_match,
        path: scored.path,
      };
    }
  }

  return bestResult ?? { found: false };
}

// ---------------------------------------------------------------------------
// Path scoring — pure function, exported for testability
// ---------------------------------------------------------------------------

type ScoredPath = {
  weight: number;
  loose_match: boolean;
  path: { nodes: PathNode[]; edges: PathEdge[]; weight: number };
};

/**
 * Score a single raw path row per the spec §5.6 rules.
 *
 * Returns `null` if the path is invalid under the given mode (e.g., traverses
 * an excluded intermediate type in default mode).
 */
export function scorePath(row: RawPathRow, loose: boolean): ScoredPath | null {
  const { node_ids, node_types, node_labels, edge_types } = row;

  // Sanity: a simple path has N nodes and N-1 edges.
  if (node_ids.length < 2 || edge_types.length !== node_ids.length - 1) {
    return null;
  }

  const nodes: PathNode[] = node_ids.map((id, i) => ({
    id,
    type: node_types[i] ?? "Unknown",
    label: node_labels[i] ?? id,
  }));

  const edges: PathEdge[] = [];
  let total = 0;
  let looseMatch = false;

  for (let i = 0; i < edge_types.length; i++) {
    const edgeType = edge_types[i];
    const isUniversal = LOOSE_ONLY_EDGES.has(edgeType);
    const baseWeight = EDGE_WEIGHTS[edgeType];

    let edgeWeight: number;
    if (isUniversal) {
      if (!loose) return null; // universal edges never traverse in default mode
      edgeWeight = LOOSE_WEIGHT;
      looseMatch = true;
    } else if (baseWeight !== undefined) {
      edgeWeight = baseWeight;
    } else if (loose) {
      // Unknown edge — only admit under loose at loose weight.
      edgeWeight = LOOSE_WEIGHT;
      looseMatch = true;
    } else {
      return null;
    }

    // Intermediate-type check — the far end of this segment is an intermediate
    // node unless it's the final segment (endpoint is allowed).
    const isLastSegment = i === edge_types.length - 1;
    if (!isLastSegment) {
      const intermediateType = node_types[i + 1];
      if (EXCLUDED_INTERMEDIATE_TYPES.has(intermediateType)) {
        if (!loose) return null;
        looseMatch = true;
      }
    }

    edges.push({
      source: node_ids[i],
      target: node_ids[i + 1],
      type: edgeType,
      weight: edgeWeight,
    });
    total += edgeWeight;
  }

  return {
    weight: total,
    loose_match: looseMatch,
    path: { nodes, edges, weight: total },
  };
}
