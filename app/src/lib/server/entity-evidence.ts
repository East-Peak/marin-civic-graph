// Loads Records that evidence a given entity. Records are excluded from the
// Phase-2 neighborhood (see entity-loader.ts § Tier 1 / § Tier 2), so the
// evidence drawer loads them with a dedicated query.
//
// The display contract (§7.1 item 10) assumes these fields are already
// populated on each Record by the normalizer:
//   preferred_public_url, preferred_display_artifact, has_public_source.

import "server-only";
import { runQuery } from "@/lib/neo4j";
import { getSubstrateDb, servingBackend } from "@/lib/server/substrate";

export type EvidenceRecord = {
  id: string;
  record_type: string;
  captured_at: string | null;
  preferred_public_url: string | null;
  preferred_display_artifact: string | null;
  has_public_source: boolean;
};

type Neo4jRecordLike = { get(key: string): unknown };

type EvidenceSqlRow = {
  id: string;
  record_type: string | null;
  captured_at: string | null;
  preferred_public_url: string | null;
  preferred_display_artifact: string | null;
  has_public_source: unknown;
};

function boolFromSql(value: unknown): boolean {
  return value === true || value === 1 || value === "1" || value === "true";
}

export async function loadEvidence(entityId: string): Promise<EvidenceRecord[]> {
  if (servingBackend() === "substrate") {
    const rows = getSubstrateDb()
      .prepare(
        `
        SELECT
          r.id AS id,
          json_extract(r.props, '$.record_type') AS record_type,
          json_extract(r.props, '$.captured_at') AS captured_at,
          json_extract(r.props, '$.preferred_public_url') AS preferred_public_url,
          json_extract(r.props, '$.preferred_display_artifact') AS preferred_display_artifact,
          json_extract(r.props, '$.has_public_source') AS has_public_source
        FROM edges evidence
        JOIN nodes r
          ON r.id = evidence.target
         AND r.type = 'Record'
        WHERE evidence.source = @entityId
          AND evidence.rel = 'EVIDENCED_BY'
        ORDER BY (captured_at IS NULL) DESC, captured_at DESC, r.id ASC
        LIMIT 50
        `,
      )
      .all({ entityId }) as EvidenceSqlRow[];

    return rows.map((row) => ({
      id: row.id,
      record_type: String(row.record_type ?? "record"),
      captured_at: row.captured_at ?? null,
      preferred_public_url: row.preferred_public_url ?? null,
      preferred_display_artifact: row.preferred_display_artifact ?? null,
      has_public_source: boolFromSql(row.has_public_source),
    }));
  }

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
