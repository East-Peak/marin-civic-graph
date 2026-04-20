// app/src/lib/server/search-backend.ts
//
// Shared search backend for /api/search and the /search page.
// Both callers invoke runSearch(q, includeRecords) directly — the page does
// NOT HTTP-self-fetch the API route.
//
// Per spec §3.3: bucketed results — exact-id match (always at top, even with
// include_records=false) → entity bucket → record bucket (only when
// include_records=true). The full-text index is `openmarin_search_index`.

import "server-only";
import { runQuery } from "@/lib/neo4j";
import { urlSegmentForType, type NodeType } from "@/lib/type-display";
import { canonicalType } from "@/lib/canonical-type";

export const MAX_Q_LENGTH = 500;

export type SearchResult = {
  id: string;
  type: NodeType;
  search_label: string;
  route: string;
  key_fact: string | null;
  last_activity: string | null;
  jurisdiction: string | null;
  rank: number;
};

export type SearchResponse = {
  query: string;
  built_at: string;
  results: SearchResult[];
};

type Neo4jNode = {
  properties: Record<string, unknown>;
  labels: string[];
};

// Escape Lucene reserved chars so reserved operators don't blow up the query.
// Per Lucene docs: + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
export function escapeLucene(q: string): string {
  return q
    .replace(/([+\-!(){}\[\]^"~*?:\\/])/g, "\\$1")
    .replace(/&&/g, "\\&&")
    .replace(/\|\|/g, "\\||");
}

function nodeToResult(node: Neo4jNode): SearchResult {
  const props = node.properties;
  const id = String(props.id);
  const type = canonicalType(node.labels, id) ?? "Person";
  const slug = id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
  const urlType = urlSegmentForType(type);
  return {
    id,
    type,
    search_label: String(props.search_label ?? id),
    route: `/${urlType}/${slug}`,
    key_fact: (props.search_key_fact as string) ?? null,
    last_activity: (props.search_last_activity as string) ?? null,
    jurisdiction: (props.jurisdiction_name as string) ?? null,
    rank: Number(props.search_rank ?? 0),
  };
}

/**
 * Execute the bucketed search query against AuraDB.
 *
 * Ordering contract (per spec §3.3):
 *   1. exact-id match (always first, even if include_records=false)
 *   2. entity bucket (never Records, ordered by Lucene score * 100 + search_rank)
 *   3. record bucket (only when include_records=true)
 */
export async function runSearch(
  q: string,
  includeRecords: boolean,
): Promise<SearchResponse> {
  const qLucene = escapeLucene(q);
  const cypher = `
    // Stage 0: exact id (bypasses include_records)
    OPTIONAL MATCH (exact {id: $q})
    WITH exact
    WITH CASE WHEN exact IS NULL THEN [] ELSE [exact] END AS exact_list

    // Stage 1: entity bucket (never Records)
    CALL {
      WITH $q_lucene AS q
      CALL db.index.fulltext.queryNodes('openmarin_search_index', q) YIELD node, score
      WHERE NOT node:Record
      WITH node, score
      ORDER BY score DESC
      LIMIT 200
      WITH node, score, (score * 100 + coalesce(node.search_rank, 0)) AS combined_rank
      ORDER BY combined_rank DESC, node.id ASC
      LIMIT 50
      RETURN collect(node) AS entity_results
    }

    // Stage 2: record bucket
    CALL {
      WITH $q_lucene AS q, $include_records AS include_records
      CALL db.index.fulltext.queryNodes('openmarin_search_index', q) YIELD node, score
      WHERE include_records AND node:Record
      WITH node, score
      ORDER BY score DESC
      LIMIT 200
      WITH node, score, (score * 100 + coalesce(node.search_rank, 0)) AS combined_rank
      ORDER BY combined_rank DESC, node.captured_at DESC, node.id ASC
      LIMIT 50
      RETURN collect(node) AS record_results
    }

    WITH exact_list,
         [n IN entity_results WHERE NOT n IN exact_list] AS entities_deduped,
         [n IN record_results WHERE NOT n IN exact_list] AS records_deduped
    WITH (exact_list + entities_deduped + records_deduped)[..50] AS results
    RETURN results
  `;

  const records = await runQuery(cypher, {
    q,
    q_lucene: qLucene,
    include_records: includeRecords,
  });
  const nodes = records[0]?.get("results") as Neo4jNode[] | undefined;
  const results = (nodes ?? []).map(nodeToResult);
  return {
    query: q,
    built_at: new Date().toISOString(),
    results,
  };
}
