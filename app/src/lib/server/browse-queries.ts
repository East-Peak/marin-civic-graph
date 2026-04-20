// app/src/lib/server/browse-queries.ts
//
// Per-type paginated browse query — used by /api/browse/[type] and
// /browse/[type]/page.tsx. Both callers invoke runBrowseQuery() directly;
// the page does NOT HTTP-self-fetch the API route.
//
// Cursor-based pagination: rows are ordered by id ASC. The cursor is the
// last-seen id from the previous page; the caller passes it in to resume.
// Cursors are opaque strings — do not parse or mutate client-side.
//
// Per-type columns come from `factsForEntity` in entity-facts.ts — we pull
// the first two non-ID fact keys so the browse table mirrors the facts-panel
// schema every entity page uses.

import "server-only";
import neo4j from "neo4j-driver";
import { ALL_TYPES, type NodeType } from "@/lib/type-display";
import { factsForEntity } from "@/lib/server/entity-facts";
import { runQuery } from "@/lib/neo4j";
import { urlSegmentForType } from "@/lib/type-display";

export const DEFAULT_LIMIT = 50;
export const MAX_LIMIT = 200;
export const MAX_SEARCH_LENGTH = 500;

export type BrowseColumn = {
  key: string;
  label: string;
};

export type BrowseRow = {
  id: string;
  type: NodeType;
  search_label: string;
  route: string;
  [columnKey: string]: unknown;
};

export type BrowseQueryOptions = {
  type: NodeType;
  cursor?: string;
  limit?: number;
  search?: string;
};

export type BuiltBrowseQuery = {
  cypher: string;
  params: Record<string, unknown>;
  columns: BrowseColumn[];
};

export type BrowseResult = {
  rows: BrowseRow[];
  next_cursor: string | null;
  columns: BrowseColumn[];
};

// ---------------------------------------------------------------------------
// Column derivation
// ---------------------------------------------------------------------------

/**
 * Return the ordered list of browse-table columns for a given NodeType.
 *
 * Contract:
 *   - Always starts with `search_label` (rendered as a link in the UI).
 *   - Appends up to two per-type fact keys pulled from factsForEntity().
 *     The "Name" fact is skipped because it duplicates search_label.
 *   - Never includes the ID (shown inline under search_label in the table).
 */
export function columnsForType(type: NodeType): BrowseColumn[] {
  const base: BrowseColumn[] = [{ key: "search_label", label: "Name" }];
  // Invoke factsForEntity with an empty prop bag just to read the row keys.
  const sample = factsForEntity(type, {});
  const extras: BrowseColumn[] = [];
  for (const row of sample) {
    if (row.key === "ID" || row.key === "Name") continue;
    if (extras.length >= 2) break;
    extras.push({ key: propKeyForFactLabel(type, row.key), label: row.key });
  }
  return [...base, ...extras];
}

/**
 * Map a fact-row label (e.g., "Current seat") back to the underlying node
 * property (e.g., "current_seat_display"). Mirror of the case-by-case
 * mapping inside factsForEntity — kept small and explicit.
 *
 * The Cypher browse query RETURNs these property keys verbatim, so the
 * browse-table can pull row[col.key] with no further transformation.
 */
function propKeyForFactLabel(type: NodeType, label: string): string {
  const key = label.toLowerCase();
  const MAP: Record<NodeType, Record<string, string>> = {
    Person: {
      "current seat": "current_seat_display",
      jurisdiction: "jurisdiction_name",
      aliases: "aliases",
    },
    Decision: {
      decided: "decided_at",
      institution: "institution_name",
      vote: "vote_summary",
      status: "status",
    },
    Project: {
      status: "status",
      address: "address",
      jurisdiction: "jurisdiction_name",
    },
    Program: {
      status: "status",
      type: "program_type",
      jurisdiction: "jurisdiction_name",
    },
    Case: {
      caption: "caption",
      docket: "docket_number",
      filed: "filed_at",
      closed: "closed_at",
      status: "status",
    },
    Meeting: {
      title: "title",
      date: "meeting_date",
      institution: "institution_name",
      type: "meeting_type",
    },
    Filing: {
      type: "filing_type",
      signed: "signed_at",
      period: "period_start",
      filer: "filed_by_name",
    },
    Committee: {
      "fppc id": "fppc_id",
      treasurer: "treasurer",
      candidate: "candidate_name",
    },
    Organization: {
      subtype: "subtype",
      jurisdiction: "jurisdiction_name",
      website: "website",
    },
    MoneyFlow: {
      amount: "amount",
      date: "flow_date",
      type: "flow_type",
      schedule: "source_schedule",
    },
    Seat: {
      title: "title",
      institution: "institution_name",
      jurisdiction: "jurisdiction_name",
    },
    SeatService: {
      seat: "seat_title",
      person: "person_name",
      start: "start_date",
      end: "end_date",
    },
    Election: {
      title: "name",
      date: "election_date",
      type: "election_type",
      jurisdiction: "jurisdiction_name",
    },
    Candidacy: {
      candidate: "person_name",
      seat: "seat_title",
      election: "election_name",
      outcome: "outcome",
    },
    AgendaItem: {
      heading: "heading",
      meeting: "meeting_title",
      date: "meeting_date",
      item: "item_number",
    },
    Proceeding: {
      title: "title",
      date: "proceeding_date",
      case: "case_caption",
      type: "proceeding_type",
    },
    Agreement: {
      title: "title",
      type: "agreement_type",
      effective: "effective_date",
      parties: "parties",
    },
    Amendment: {
      title: "title",
      parent: "parent_title",
      effective: "effective_date",
    },
    Record: {
      "record type": "record_type",
      captured: "captured_at",
      artifact: "preferred_display_artifact",
      "public url": "preferred_public_url",
    },
    Place: {
      type: "place_type",
      parent: "parent_name",
    },
    Issue: {
      description: "description",
    },
  };
  return MAP[type][key] ?? key.replace(/\s+/g, "_");
}

// ---------------------------------------------------------------------------
// Query builder
// ---------------------------------------------------------------------------

/**
 * Build the Cypher + params for a single browse-page fetch. The query
 * returns `limit + 1` is NOT used — callers always read exactly `limit` rows
 * and determine next_cursor from the last row's id if the page is full.
 */
export function buildBrowseQuery(opts: BrowseQueryOptions): BuiltBrowseQuery {
  const { type } = opts;
  const limit = clampLimit(opts.limit);
  const cursor = opts.cursor && opts.cursor.length > 0 ? opts.cursor : null;
  const search = opts.search && opts.search.trim().length > 0 ? opts.search.trim() : null;

  const columns = columnsForType(type);

  // Build the RETURN clause from the column list. `search_label` is handled
  // via coalesce so nodes missing the field still render a human label.
  const returnParts: string[] = [
    "n.id AS id",
    `'${type}' AS type`,
    "coalesce(n.search_label, n.name, n.id) AS search_label",
  ];
  for (const col of columns) {
    if (col.key === "search_label") continue;
    returnParts.push(`n.${col.key} AS ${col.key}`);
  }

  const cypher = `
    MATCH (n:${type})
    WHERE ($cursor IS NULL OR n.id > $cursor)
      AND ($search IS NULL OR toLower(coalesce(n.search_label, n.name, n.id)) CONTAINS toLower($search))
    RETURN ${returnParts.join(",\n           ")}
    ORDER BY n.id ASC
    LIMIT $limit
  `;

  // LIMIT requires a Neo4j INTEGER — a plain JS number is sent as FLOAT and
  // rejected with Neo.ClientError.Statement.ArgumentError. Wrap via neo4j.int.
  // See commit 945dc2e for the same fix in explorer-queries.ts.
  const params: Record<string, unknown> = {
    cursor,
    search,
    limit: neo4j.int(limit),
  };

  return { cypher, params, columns };
}

export function clampLimit(raw: unknown): number {
  const n = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_LIMIT;
  return Math.min(Math.floor(n), MAX_LIMIT);
}

// ---------------------------------------------------------------------------
// Executor
// ---------------------------------------------------------------------------

function toJsValue(v: unknown): unknown {
  if (v == null) return null;
  if (typeof v === "object" && v !== null && "toNumber" in v) {
    try {
      return (v as { toNumber(): number }).toNumber();
    } catch {
      return Number(v);
    }
  }
  return v;
}

export async function runBrowseQuery(opts: BrowseQueryOptions): Promise<BrowseResult> {
  const { type } = opts;
  const { cypher, params, columns } = buildBrowseQuery(opts);
  const records = await runQuery(cypher, params);
  const limit = clampLimit(opts.limit);
  const urlType = urlSegmentForType(type);

  const rows: BrowseRow[] = records.map((r) => {
    const id = String(r.get("id"));
    const slug = id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
    const row: BrowseRow = {
      id,
      type,
      search_label: String(r.get("search_label") ?? id),
      route: `/${urlType}/${slug}`,
    };
    for (const col of columns) {
      if (col.key === "search_label") continue;
      row[col.key] = toJsValue(r.get(col.key));
    }
    return row;
  });

  const nextCursor = rows.length === limit ? rows[rows.length - 1].id : null;

  return { rows, next_cursor: nextCursor, columns };
}

// ---------------------------------------------------------------------------
// URL-segment → canonical NodeType mapping
// ---------------------------------------------------------------------------

export function nodeTypeForUrlSegment(seg: string): NodeType | null {
  return ALL_TYPES.find((t) => urlSegmentForType(t) === seg) ?? null;
}
