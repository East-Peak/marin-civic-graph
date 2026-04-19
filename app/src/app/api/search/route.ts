// app/src/app/api/search/route.ts
import { runQuery } from "@/lib/neo4j";
import { jsonError } from "@/lib/api-errors";
import { urlSegmentForType, type NodeType } from "@/lib/type-display";
import { canonicalType } from "@/lib/canonical-type";

// Escape Lucene query syntax so reserved chars don't become operators.
// Per Lucene docs: + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
function escapeLucene(q: string): string {
  return q
    .replace(/([+\-!(){}\[\]^"~*?:\\/])/g, "\\$1")
    .replace(/&&/g, "\\&&")
    .replace(/\|\|/g, "\\||");
}

const MAX_Q_LENGTH = 500;

type Neo4jNode = {
  properties: Record<string, unknown>;
  labels: string[];
};

type SearchResult = {
  id: string;
  type: NodeType;
  search_label: string;
  route: string;
  key_fact: string | null;
  last_activity: string | null;
  jurisdiction: string | null;
  rank: number;
};

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

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = (searchParams.get("q") ?? "").trim();
  const includeRecords = searchParams.get("include_records") === "true";
  if (!q) return jsonError("q required", 400);
  if (q.length > MAX_Q_LENGTH) return jsonError("q too long", 400);

  const qLucene = escapeLucene(q);

  // Bucketed query per spec §3.3.
  // $q is the raw input (for exact-id match).
  // $q_lucene is Lucene-escaped (for full-text index calls).
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

  try {
    const records = await runQuery(cypher, { q, q_lucene: qLucene, include_records: includeRecords });
    const nodes = records[0]?.get("results") as Neo4jNode[] | undefined;
    const results = (nodes ?? []).map(nodeToResult);
    return Response.json({
      query: q,
      built_at: new Date().toISOString(),
      results,
    });
  } catch (err) {
    // Log the real error server-side for debugging; return a generic message to the client.
    console.error("search error", err);
    return jsonError("search failed", 500);
  }
}
