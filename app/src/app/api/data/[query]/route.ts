// GET /api/data/{slug}?{filters...}
//
// Runs one of the 10 predefined data-explorer queries. The slug is looked up
// in DATA_QUERIES; unknown slugs return 404. Only filter keys declared by the
// query are read from the URL — unknown filter keys are rejected with 400 so
// a caller can't smuggle extra data into the Cypher builder.
//
// Response:
//   { slug, built_at, columns, rows }
//
// Neo4j Integer values are coerced to JS number via toNumber() so the JSON
// output is plain numeric (same pattern as homepage-data.ts / entity-loader.ts).

import { runQuery } from "@/lib/neo4j";
import { jsonError } from "@/lib/api-errors";
import { findDataQuery, applyFilterDefaults } from "@/lib/server/data-queries";

const MAX_SLUG_LENGTH = 100;
const MAX_FILTER_VALUE_LENGTH = 500;

// Mirror toNumber() in entity-loader.ts — Neo4j's `Integer` type has a
// `.toNumber()` method; bare numbers pass through via Number().
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

export async function GET(
  req: Request,
  { params }: { params: Promise<{ query: string }> },
) {
  const { query: slug } = await params;
  if (!slug || slug.length > MAX_SLUG_LENGTH) {
    return jsonError("invalid slug", 400);
  }

  const def = findDataQuery(slug);
  if (!def) return jsonError("query not found", 404);

  const { searchParams } = new URL(req.url);
  const allowedKeys = new Set(def.filters.map((f) => f.key));

  // Reject unknown filter keys outright — we don't want callers shipping
  // unexpected fields through to the Cypher builder.
  for (const key of searchParams.keys()) {
    if (!allowedKeys.has(key)) {
      return jsonError(`unknown filter: ${key}`, 400);
    }
  }

  // Collect raw values and validate lengths.
  const rawFilters: Record<string, string> = {};
  for (const f of def.filters) {
    const value = searchParams.get(f.key);
    if (value == null) continue;
    if (value.length > MAX_FILTER_VALUE_LENGTH) {
      return jsonError(`filter too long: ${f.key}`, 400);
    }
    rawFilters[f.key] = value;
  }

  // Enforce required filters.
  for (const f of def.filters) {
    if (f.required && !rawFilters[f.key]) {
      return jsonError(`filter required: ${f.key}`, 400);
    }
  }

  const filters = applyFilterDefaults(def, rawFilters);
  const { query, params: cypherParams } = def.cypher(filters);

  try {
    const records = await runQuery(query, cypherParams);
    const rows = records.map((r) => {
      const row: Record<string, unknown> = {};
      for (const col of def.columns) {
        row[col.key] = toJsValue(r.get(col.key));
      }
      return row;
    });
    return Response.json({
      slug,
      built_at: new Date().toISOString(),
      columns: def.columns,
      rows,
    });
  } catch (err) {
    console.error(`/api/data/${slug} failed:`, err);
    return jsonError("query failed", 500);
  }
}
