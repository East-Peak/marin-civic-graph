// Loads Records that evidence a given entity. Records are excluded from the
// Phase-2 neighborhood (see entity-loader.ts § Tier 1 / § Tier 2), so the
// evidence drawer loads them with a dedicated query.
//
// The display contract (§7.1 item 10) assumes these fields are already
// populated on each Record by the normalizer:
//   preferred_public_url, preferred_display_artifact, has_public_source.

import "server-only";
import { runQuery } from "@/lib/neo4j";

export type EvidenceRecord = {
  id: string;
  record_type: string;
  captured_at: string | null;
  preferred_public_url: string | null;
  preferred_display_artifact: string | null;
  has_public_source: boolean;
};

type Neo4jRecordLike = { get(key: string): unknown };

export async function loadEvidence(entityId: string): Promise<EvidenceRecord[]> {
  const records = (await runQuery(
    `
    MATCH (n {id: $entityId})-[:EVIDENCED_BY]->(r:Record)
    RETURN r
    ORDER BY r.captured_at DESC
    LIMIT 50
    `,
    { entityId },
  )) as unknown as Neo4jRecordLike[];
  return records.map((rec) => {
    const node = rec.get("r") as { properties: Record<string, unknown> };
    const r = node.properties;
    return {
      id: String(r.id),
      record_type: String(r.record_type ?? "record"),
      captured_at: (r.captured_at as string) ?? null,
      preferred_public_url: (r.preferred_public_url as string) ?? null,
      preferred_display_artifact: (r.preferred_display_artifact as string) ?? null,
      has_public_source: Boolean(r.has_public_source),
    };
  });
}
