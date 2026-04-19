// app/src/app/api/catalog/route.ts
import { runQuery } from "@/lib/neo4j";
import { ALL_TYPES, type NodeType } from "@/lib/type-display";

export async function GET() {
  const labels = ALL_TYPES;
  const records = await runQuery(
    `
    UNWIND $labels AS label
    CALL {
      WITH label
      CALL apoc.cypher.run('MATCH (n:' + label + ') RETURN count(n) AS c', {}) YIELD value
      RETURN value.c AS c
    }
    RETURN label, c AS count
    `,
    { labels },
  );

  const toNumber = (v: unknown): number =>
    typeof v === "object" && v !== null && "toNumber" in v
      ? (v as { toNumber(): number }).toNumber()
      : Number(v);

  const counts = Object.fromEntries(
    records.map((r) => [r.get("label") as NodeType, toNumber(r.get("count"))]),
  ) as Record<NodeType, number>;

  return Response.json({
    built_at: new Date().toISOString(),
    counts,
  });
}
