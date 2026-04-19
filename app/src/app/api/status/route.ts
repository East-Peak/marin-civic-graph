// app/src/app/api/status/route.ts
import { runQuery } from "@/lib/neo4j";
import { readFile } from "node:fs/promises";
import path from "node:path";

// SUBGRAPHS timestamp comes from the static manifest copied into public/ by prebuild.
// Reading from public/ means process.cwd() resolution is stable across dev and Vercel.
async function readSubgraphsBuiltAt(): Promise<string | null> {
  try {
    const manifestPath = path.join(process.cwd(), "public", "subgraphs", "manifest.json");
    const content = await readFile(manifestPath, "utf-8");
    return (JSON.parse(content) as { built_at: string }).built_at;
  } catch {
    return null;
  }
}

export async function GET() {
  const subgraphsBuiltAt = (await readSubgraphsBuiltAt()) ?? null;

  try {
    const records = await runQuery(
      `
      MATCH (n)
      WITH count(n) AS node_count
      MATCH ()-[r]->()
      WITH node_count, count(r) AS edge_count
      MATCH (p:Place) WHERE p.place_type IN ['city', 'county']
      WITH node_count, edge_count, count(p) AS jurisdiction_count
      OPTIONAL MATCH (n) WHERE n.captured_at IS NOT NULL
      RETURN node_count, edge_count, jurisdiction_count,
             toString(max(n.captured_at)) AS ingest_at
      `,
    );

    const record = records[0];
    const toNumber = (v: unknown): number =>
      typeof v === "object" && v !== null && "toNumber" in v
        ? (v as { toNumber(): number }).toNumber()
        : Number(v);

    return Response.json({
      connected: true,
      node_count: toNumber(record.get("node_count")),
      edge_count: toNumber(record.get("edge_count")),
      jurisdiction_count: toNumber(record.get("jurisdiction_count")),
      ingest_at: record.get("ingest_at"),
      subgraphs_built_at: subgraphsBuiltAt,
    });
  } catch {
    return Response.json({
      connected: false,
      node_count: 0,
      edge_count: 0,
      jurisdiction_count: 0,
      ingest_at: null,
      subgraphs_built_at: subgraphsBuiltAt,
    });
  }
}
