// Shared server-only data loaders used by the homepage page.tsx AND /api/status.
// Server components call these directly (no HTTP self-fetch); /api/status wraps them for external callers.

import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { runQuery } from "@/lib/neo4j";
import type { NodeType } from "@/lib/type-display";

export type StatusPayload = {
  connected: boolean;
  node_count: number;
  edge_count: number;
  jurisdiction_count: number;
  ingest_at: string | null;
  subgraphs_built_at: string | null;
};

export type CatalogPayload = {
  built_at: string;
  counts: Partial<Record<NodeType, number>>;
};

function toNumber(v: unknown): number {
  return typeof v === "object" && v !== null && "toNumber" in v
    ? (v as { toNumber(): number }).toNumber()
    : Number(v);
}

async function readManifestBuiltAt(): Promise<string | null> {
  try {
    const manifestPath = path.join(process.cwd(), "public", "subgraphs", "manifest.json");
    const content = await readFile(manifestPath, "utf-8");
    return (JSON.parse(content) as { built_at: string }).built_at;
  } catch {
    return null;
  }
}

export async function loadStatus(): Promise<StatusPayload> {
  const subgraphsBuiltAt = await readManifestBuiltAt();
  try {
    const records = await runQuery(
      `
      OPTIONAL MATCH (s:_SyncState {kind: 'ingest'})
      WITH s
      MATCH (n)
      WITH s, count(n) AS node_count
      MATCH ()-[r]->()
      WITH s, node_count, count(r) AS edge_count
      MATCH (p:Place) WHERE p.place_type IN ['city', 'county']
      RETURN node_count, edge_count, count(p) AS jurisdiction_count,
             s.updated_at AS ingest_at
      `,
    );
    const record = records[0];
    return {
      connected: true,
      node_count: toNumber(record.get("node_count")),
      edge_count: toNumber(record.get("edge_count")),
      jurisdiction_count: toNumber(record.get("jurisdiction_count")),
      ingest_at: record.get("ingest_at"),
      subgraphs_built_at: subgraphsBuiltAt,
    };
  } catch {
    return {
      connected: false,
      node_count: 0,
      edge_count: 0,
      jurisdiction_count: 0,
      ingest_at: null,
      subgraphs_built_at: subgraphsBuiltAt,
    };
  }
}

export async function loadCatalog(): Promise<CatalogPayload> {
  try {
    const catalogPath = path.join(process.cwd(), "public", "catalog.json");
    const content = await readFile(catalogPath, "utf-8");
    return JSON.parse(content) as CatalogPayload;
  } catch {
    return { built_at: new Date().toISOString(), counts: {} };
  }
}
