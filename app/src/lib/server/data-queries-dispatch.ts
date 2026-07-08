import "server-only";

import { runQuery } from "@/lib/neo4j";
import type { DataQueryDef } from "@/lib/server/data-queries";
import { runDataQuerySql } from "@/lib/server/data-queries-sql";
import { servingBackend } from "@/lib/server/substrate";

export type ExecutedDataQuery = {
  rows: Record<string, unknown>[];
  as_of_date?: string;
};

// Neo4j Integer values need to be serialized as plain JS numbers before they
// cross either the API route or the server-rendered /data page boundary.
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

export async function executeDataQuery(
  def: DataQueryDef,
  filters: Record<string, string>,
): Promise<ExecutedDataQuery> {
  if (servingBackend() === "substrate") {
    return runDataQuerySql(def, filters);
  }

  const { query, params } = def.cypher(filters);
  const records = await runQuery(query, params);
  const rows = records.map((record) => {
    const row: Record<string, unknown> = {};
    for (const col of def.columns) {
      row[col.key] = toJsValue(record.get(col.key));
    }
    return row;
  });
  return { rows };
}
