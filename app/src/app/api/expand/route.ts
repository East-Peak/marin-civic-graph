// GET /api/expand?focus={id}&hop=1|2|3|4
//                &excluded_node_types=A,B&excluded_edge_types=X,Y
//                &already_loaded={id1,id2,...}
//
// Click-expand (hop=1) and right-click-expand-all (hop=2..4) both hit this
// endpoint. Returns the newly-discovered nodes + any whitelist edges among
// the union (focus + already-loaded + new).
//
// Thin wrapper around `buildExpandQuery` (lib/server/explorer-queries.ts).
// Edge fetch uses `buildEdgesAmongSelectedQuery` from entity-queries.ts so
// the explorer's edge rendering matches the entity page's.

import { runQuery } from "@/lib/neo4j";
import {
  buildExpandQuery,
  UNIVERSAL_EXPAND_EDGES,
} from "@/lib/server/explorer-queries";
import { buildEdgesAmongSelectedQuery } from "@/lib/server/entity-queries";
import {
  MONEY_EDGES_LIVE,
  LEGAL_EDGES_LIVE,
  PHASE2_WHITELIST_LIVE,
} from "@/lib/edge-vocabulary";
import { jsonError } from "@/lib/api-errors";
import { canonicalType } from "@/lib/canonical-type";
import { urlSegmentForType, ALL_TYPES, type NodeType } from "@/lib/type-display";

// ---------------------------------------------------------------------------
// Shared edge-style classifier — mirrors entity-loader.ts. Kept local so the
// explorer route doesn't need to import from entity-loader (which is
// 'server-only' and pulls a wide dependency chain).
// ---------------------------------------------------------------------------

const MONEY_EDGES = new Set(MONEY_EDGES_LIVE);
const LEGAL_EDGES = new Set(LEGAL_EDGES_LIVE);

type EdgeStyle = "governance" | "money" | "legal-constrains";

function classifyEdgeStyle(relType: string): EdgeStyle {
  if (MONEY_EDGES.has(relType)) return "money";
  if (LEGAL_EDGES.has(relType)) return "legal-constrains";
  return "governance";
}

function routeFor(id: string, type: NodeType): string {
  const slug = id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
  return `/${urlSegmentForType(type)}/${slug}`;
}

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

const VALID_TYPES: ReadonlySet<string> = new Set(ALL_TYPES);

function parseList(raw: string | null): string[] {
  return (raw ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function parseNodeTypes(raw: string | null): NodeType[] {
  // Unknown type names are silently dropped — an attacker wedging an invalid
  // type into the URL shouldn't 500 the endpoint.
  return parseList(raw).filter((t): t is NodeType => VALID_TYPES.has(t));
}

// ---------------------------------------------------------------------------
// GET handler
// ---------------------------------------------------------------------------

type NeighborRow = {
  id: string;
  type: NodeType;
  label: string;
  route: string;
  ring: number;
  /** ISO date of the effective event for this candidate, or null for durable
   *  types (Person, Organization, Place, etc.). Clients use this to plumb
   *  each expanded neighbor into the time slider (§5.4). */
  event_date: string | null;
};

type EdgeRow = {
  source: string;
  target: string;
  type: string;
  style: EdgeStyle;
};

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const focus = searchParams.get("focus")?.trim();
  const hopStr = searchParams.get("hop") ?? "1";
  const hop = Number(hopStr);

  if (!focus || !Number.isInteger(hop) || hop < 1 || hop > 4) {
    return jsonError("focus + hop (1-4) required", 400);
  }

  const excludedNodeTypes = parseNodeTypes(searchParams.get("excluded_node_types"));
  const excludedEdgeTypes = parseList(searchParams.get("excluded_edge_types"));
  const alreadyLoadedIds = parseList(searchParams.get("already_loaded"));
  const includeUniversals = searchParams.get("include_universals") === "true";

  try {
    const { cypher, params, cap } = buildExpandQuery({
      focusId: focus,
      hopLimit: hop as 1 | 2 | 3 | 4,
      excludedNodeTypes,
      excludedEdgeTypes,
      alreadyLoadedIds,
      includeUniversals,
    });

    const records = await runQuery(cypher, params);

    const nodes: NeighborRow[] = [];
    for (const r of records) {
      const labels = (r.get("labels") as string[]) ?? [];
      const id = String(r.get("id"));
      const type = canonicalType(labels, id);
      if (!type) continue; // defensive: skip rows we can't classify
      // event_date projection may be absent on the degenerate "every type
      // excluded" path — default to null so callers get a consistent shape.
      const rawEventDate = (() => {
        try {
          return r.get("event_date");
        } catch {
          return null;
        }
      })();
      const eventDate =
        typeof rawEventDate === "string" && rawEventDate.length > 0
          ? rawEventDate
          : null;
      nodes.push({
        id,
        type,
        label: String(r.get("label") ?? id),
        route: routeFor(id, type),
        ring: Number(r.get("ring") ?? 1),
        event_date: eventDate,
      });
    }

    // Fetch whitelist edges among the union (focus + already-loaded + new).
    // Honor excluded_edge_types by filtering the passed whitelist.
    const unionIds = Array.from(
      new Set<string>([focus, ...alreadyLoadedIds, ...nodes.map((n) => n.id)]),
    );

    const edges: EdgeRow[] = [];
    if (unionIds.length >= 2) {
      const baseWhitelist = PHASE2_WHITELIST_LIVE.filter(
        (e) => !excludedEdgeTypes.includes(e),
      );
      const allowedEdges = includeUniversals
        ? Array.from(
            new Set<string>([
              ...baseWhitelist,
              ...UNIVERSAL_EXPAND_EDGES.filter((e) => !excludedEdgeTypes.includes(e)),
            ]),
          )
        : baseWhitelist;
      const edgeRecords = await runQuery(buildEdgesAmongSelectedQuery(), {
        ids: unionIds,
        whitelist: allowedEdges,
      });
      for (const r of edgeRecords) {
        const relType = String(r.get("rel_type"));
        edges.push({
          source: String(r.get("start_id") ?? r.get("source")),
          target: String(r.get("end_id") ?? r.get("target")),
          type: relType,
          style: classifyEdgeStyle(relType),
        });
      }
    }

    return Response.json({
      nodes,
      edges,
      new_count: nodes.length,
      cap,
    });
  } catch (err) {
    console.error("/api/expand failed:", err);
    return jsonError("expand failed", 500);
  }
}
