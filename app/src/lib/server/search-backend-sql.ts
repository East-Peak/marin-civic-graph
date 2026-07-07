import "server-only";

import { canonicalType } from "@/lib/canonical-type";
import { getSubstrateDb } from "@/lib/server/substrate";
import { urlSegmentForType } from "@/lib/type-display";
import type { SearchResponse, SearchResult } from "@/lib/server/search-backend";

const SEARCH_LIMIT = 50;

type StoredSearchNode = {
  id: string;
  type: string;
  search_label: string | null;
  props: string;
};

export function buildFtsQuery(q: string): string | null {
  const terms = q
    .toLowerCase()
    .split(/\s+/)
    .filter((term) => term.length > 0);
  if (terms.length === 0) return null;
  return terms.map((term) => `"${term.replaceAll('"', '""')}"`).join(" OR ");
}

function slugForId(id: string): string {
  return id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
}

function nullableString(value: unknown): string | null {
  return value == null ? null : String(value);
}

function propsForRow(row: StoredSearchNode): Record<string, unknown> {
  return JSON.parse(row.props) as Record<string, unknown>;
}

function rowToResult(row: StoredSearchNode): SearchResult {
  const props = propsForRow(row);
  const type = canonicalType([row.type], row.id) ?? "Person";
  const searchLabel = nullableString(props.search_label) ?? row.search_label ?? row.id;
  return {
    id: row.id,
    type,
    search_label: searchLabel,
    route: `/${urlSegmentForType(type)}/${slugForId(row.id)}`,
    key_fact: nullableString(props.search_key_fact),
    last_activity: nullableString(props.search_last_activity),
    jurisdiction: nullableString(props.jurisdiction_name),
    rank: Number(props.search_rank ?? 0),
  };
}

function withoutExact(rows: StoredSearchNode[], exactIds: Set<string>): StoredSearchNode[] {
  return rows.filter((row) => !exactIds.has(row.id));
}

export async function runSearchSubstrate(
  q: string,
  includeRecords: boolean,
): Promise<SearchResponse> {
  const db = getSubstrateDb();
  const exact = db
    .prepare(
      `
        SELECT id, type, search_label, props
        FROM nodes
        WHERE id = ?
      `,
    )
    .all(q) as StoredSearchNode[];

  const ftsQuery = buildFtsQuery(q);
  const exactIds = new Set(exact.map((row) => row.id));
  let entities: StoredSearchNode[] = [];
  let records: StoredSearchNode[] = [];

  if (ftsQuery) {
    entities = db
      .prepare(
        `
          SELECT n.id, n.type, n.search_label, n.props
          FROM search_fts
          JOIN nodes n ON n.rowid = search_fts.rowid
          WHERE search_fts MATCH ?
            AND n.type != 'Record'
          ORDER BY
            bm25(search_fts) ASC,
            json_extract(n.props, '$.search_rank') DESC,
            n.id ASC
          LIMIT ?
        `,
      )
      .all(ftsQuery, SEARCH_LIMIT) as StoredSearchNode[];

    if (includeRecords) {
      records = db
        .prepare(
          `
            SELECT n.id, n.type, n.search_label, n.props
            FROM search_fts
            JOIN nodes n ON n.rowid = search_fts.rowid
            WHERE search_fts MATCH ?
              AND n.type = 'Record'
            ORDER BY
              bm25(search_fts) ASC,
              json_extract(n.props, '$.captured_at') DESC,
              n.id ASC
            LIMIT ?
          `,
        )
        .all(ftsQuery, SEARCH_LIMIT) as StoredSearchNode[];
    }
  }

  const rows = [
    ...exact,
    ...withoutExact(entities, exactIds),
    ...withoutExact(records, exactIds),
  ].slice(0, SEARCH_LIMIT);

  return {
    query: q,
    built_at: new Date().toISOString(),
    results: rows.map(rowToResult),
  };
}
