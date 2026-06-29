// Pure (React-free) bench logic for the Identity Attach Workbench (Slice 3): queue
// bucketing, the client-side bulk gate (incl. the graph collision filter), the
// decision→display-status mapping, and small display helpers. Kept separate from the
// component so it is unit-testable (see src/tests/operator/bench-logic.test.ts).
import type { Case, ContextEntry } from "./bench-types";

/** The case decorated with a session-local display status (starts at the ledger status,
 *  updates from the writer's response after each decision). */
export type BenchRow = Case & { displayStatus: string };

export type Bucket = "needsReview" | "recommended" | "rejected" | "done";

export type DecideResponse = {
  result: string; // created | existing | superseded | unsure
  assertion: { status?: string } | null;
  same_as: unknown;
};

/** Registry key field by lane (which public field holds the proposed identity key). */
export const KEY_FIELD: Record<string, string> = {
  ein: "registry_ein",
  sos_id: "sos_id",
  committee_id: "committee_id",
};

export const usd = (n: number): string => `$${Math.round(n).toLocaleString("en-US")}`;

/** The vendor org id (context is keyed by this). */
export const vendorId = (c: Case): string => c.candidate_joins[0].left_ref.local_id;

/** The proposed identity key (the registry anchor's public key field), or an em-dash. */
export function proposedKey(c: Case): string {
  const j = c.candidate_joins[0];
  const field = KEY_FIELD[j.left_ref.source_id];
  const v = field ? j.right_ref.public_fields[field] : undefined;
  return v == null || v === "" ? "—" : String(v);
}

/** The best display name: the graph's real label, falling back to the raw vendor ref. */
export function displayName(c: Case, ctx: ContextEntry | undefined): string {
  return ctx?.display_label ?? c.candidate_joins[0].left_ref.display_label;
}

/** Money-in for sorting; -1 when no context so unenriched rows sort to the bottom. */
export function moneyOf(c: Case, ctx: Record<string, ContextEntry>): number {
  return ctx[vendorId(c)]?.money_total ?? -1;
}

const REJECTED = new Set(["rejected_current_evidence", "rejected_entity_distinct"]);
const DONE = new Set(["approved", "superseded", "deterministic", "unsure"]);

/** The ledger statuses the writer can stamp — anything else echoed back is untrusted. */
const KNOWN_STATUSES = new Set([
  "none",
  "requeued",
  "approved",
  "superseded",
  "deterministic",
  "rejected_current_evidence",
  "rejected_entity_distinct",
]);

/** New display status after a decision — prefer the server's echoed assertion status (when
 *  it's a status we recognize), else derive it from the action (+ rejection kind). An
 *  unrecognized echoed status is ignored rather than trusted into a wrong bucket. Unsure
 *  is a session-only skip. */
export function statusAfter(
  action: "approve" | "reject" | "unsure",
  rejectionKind: "current_evidence" | "entity_distinct" | undefined,
  res: DecideResponse,
): string {
  if (action === "unsure") return "unsure";
  const echoed = res.assertion?.status;
  if (echoed && KNOWN_STATUSES.has(echoed)) return echoed;
  if (action === "approve") return "approved";
  return `rejected_${rejectionKind ?? "current_evidence"}`;
}

/** Can this row be cleared via the bulk path? Requires the read-model bulk flag, an
 *  unresolved status, AND a live graph confirmation of no key collision. Absent context
 *  ⇒ ineligible (we never bulk-approve without confirming no-collision). */
export function clientBulkEligible(r: BenchRow, ctx: ContextEntry | undefined): boolean {
  if (!r.bulk_eligible) return false;
  if (r.displayStatus !== "none") return false;
  if (!ctx) return false; // graph context unavailable — fail safe
  return !ctx.key_collision;
}

/** Which queue a row belongs to, given its status and whether it is bulk-recommended. */
export function bucketOf(status: string, recommended: boolean): Bucket {
  if (REJECTED.has(status)) return "rejected";
  if (DONE.has(status)) return "done";
  return recommended ? "recommended" : "needsReview"; // none | requeued
}

export type Buckets = Record<Bucket, BenchRow[]>;

/** Partition rows into the four queues. needs-review and recommended are sorted by
 *  money-in desc (then case_id); rejected/done by case_id. */
export function bucketize(rows: BenchRow[], ctx: Record<string, ContextEntry>): Buckets {
  const out: Buckets = { needsReview: [], recommended: [], rejected: [], done: [] };
  for (const r of rows) {
    out[bucketOf(r.displayStatus, clientBulkEligible(r, ctx[vendorId(r)]))].push(r);
  }
  const byMoney = (a: BenchRow, b: BenchRow) =>
    moneyOf(b, ctx) - moneyOf(a, ctx) || a.case_id.localeCompare(b.case_id);
  const byId = (a: BenchRow, b: BenchRow) => a.case_id.localeCompare(b.case_id);
  out.needsReview.sort(byMoney);
  out.recommended.sort(byMoney);
  out.rejected.sort(byId);
  out.done.sort(byId);
  return out;
}
