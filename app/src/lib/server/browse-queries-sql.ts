import "server-only";

import { urlSegmentForType } from "@/lib/type-display";
import {
  clampLimit,
  columnsForType,
  type BrowseQueryOptions,
  type BrowseResult,
  type BrowseRow,
} from "@/lib/server/browse-queries";
import { getSubstrateDb } from "@/lib/server/substrate";

type StoredBrowseRow = {
  id: string;
  search_label: string;
  col1_key: string | null;
  col1_value: string | null;
  col2_key: string | null;
  col2_value: string | null;
};

function nonEmpty(raw: string | undefined): string | null {
  if (raw == null) return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function storedValue(raw: string | null): unknown {
  return raw == null ? null : JSON.parse(raw);
}

function slugForId(id: string): string {
  return id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
}

export function runBrowseQuerySubstrate(opts: BrowseQueryOptions): BrowseResult {
  const type = opts.type;
  const columns = columnsForType(type);
  const limit = clampLimit(opts.limit);
  const cursor = nonEmpty(opts.cursor);
  const search = nonEmpty(opts.search);

  const storedRows = getSubstrateDb()
    .prepare(
      `
        SELECT id, search_label, col1_key, col1_value, col2_key, col2_value
        FROM browse_rows
        WHERE type = ?
          AND (? IS NULL OR id > ?)
          AND (? IS NULL OR instr(label_lower, lower(?)) > 0)
        ORDER BY id ASC
        LIMIT ?
      `,
    )
    .all(type, cursor, cursor, search, search, limit) as StoredBrowseRow[];

  const urlType = urlSegmentForType(type);
  const rows: BrowseRow[] = storedRows.map((stored) => {
    const values = new Map<string, unknown>();
    if (stored.col1_key != null) values.set(stored.col1_key, storedValue(stored.col1_value));
    if (stored.col2_key != null) values.set(stored.col2_key, storedValue(stored.col2_value));

    const row: BrowseRow = {
      id: stored.id,
      type,
      search_label: stored.search_label,
      route: `/${urlType}/${slugForId(stored.id)}`,
    };
    for (const col of columns) {
      if (col.key === "search_label") continue;
      row[col.key] = values.has(col.key) ? values.get(col.key) : null;
    }
    return row;
  });

  const nextCursor = rows.length === limit ? rows[rows.length - 1].id : null;
  return { rows, next_cursor: nextCursor, columns };
}
