// Operator-only server helper: the whitelisted Neo4j consequence projection. Read-only +
// redaction-safe — only public display name, money-in total, flow count, paying
// departments, and a key-collision hint. Fixed queries; params are id/anchor lists only.
// Shared by /api/reconcile/context and the bench page.
import { runQuery } from "@/lib/neo4j";

export type ContextEntry = {
  display_label: string | null;
  money_total: number;
  flow_count: number;
  departments: string[];
  key_collision: boolean;
  collides_with: string[];
};

export type ContextItem = { vendor_id: string; anchor_id?: string };

const num = (v: unknown): number =>
  v != null && typeof v === "object" && "toNumber" in (v as object)
    ? (v as { toNumber(): number }).toNumber()
    : Number(v ?? 0);

// Money-in: (m:MoneyFlow)-[:TO_TARGET]->(vendor); paying dept: (dept)-[:FROM_SOURCE]->(m).
const MONEY_Q = `
UNWIND $ids AS vid
MATCH (v:Organization {id: vid})
OPTIONAL MATCH (m:MoneyFlow)-[:TO_TARGET]->(v)
WITH vid, v, collect(m) AS flows
OPTIONAL MATCH (dept:Organization)-[:FROM_SOURCE]->(mm) WHERE mm IN flows
WITH vid, v, flows, collect(DISTINCT dept.display_label) AS depts
RETURN vid AS id,
       v.display_label AS display_label,
       size(flows) AS flow_count,
       reduce(t = 0.0, m IN flows | t + coalesce(m.amount, 0)) AS money_total,
       [x IN depts WHERE x IS NOT NULL] AS departments`;

// Collision: the proposed key-anchor already SAME_AS-linked to a different org.
const COLLISION_Q = `
UNWIND $pairs AS p
OPTIONAL MATCH (a {id: p.anchor})-[:SAME_AS]-(other:Organization) WHERE other.id <> p.vendor
WITH p, collect(DISTINCT other.id) AS others
RETURN p.vendor AS id, size(others) > 0 AS key_collision, others[..3] AS collides_with`;

export async function fetchContext(items: ContextItem[]): Promise<Record<string, ContextEntry>> {
  const valid = items.filter((i) => i?.vendor_id);
  if (valid.length === 0) return {};
  const ids = [...new Set(valid.map((i) => i.vendor_id))];
  const pairs = valid
    .filter((i) => i.anchor_id)
    .map((i) => ({ vendor: i.vendor_id, anchor: i.anchor_id as string }));

  const results: Record<string, ContextEntry> = {};
  const moneyRows = await runQuery(MONEY_Q, { ids }, { timeoutMs: 30000 });
  for (const r of moneyRows) {
    results[r.get("id")] = {
      display_label: r.get("display_label") ?? null,
      money_total: num(r.get("money_total")),
      flow_count: num(r.get("flow_count")),
      departments: (r.get("departments") as string[]) ?? [],
      key_collision: false,
      collides_with: [],
    };
  }
  if (pairs.length > 0) {
    const collRows = await runQuery(COLLISION_Q, { pairs }, { timeoutMs: 30000 });
    for (const r of collRows) {
      const id = r.get("id");
      if (results[id]) {
        results[id].key_collision = Boolean(r.get("key_collision"));
        results[id].collides_with = (r.get("collides_with") as string[]) ?? [];
      }
    }
  }
  return results;
}
