// Pure (React-free) bench logic for the Identity Attach Workbench (Slice 3): queue
// bucketing, the client-side bulk gate (incl. the graph collision filter), the
// decision→display-status mapping, and small display helpers. Kept separate from the
// component so it is unit-testable (see src/tests/operator/bench-logic.test.ts).
import { caseRefs, KEY_FIELD } from "./case-refs";
import type { Case, ContextEntry } from "./bench-types";
import {
  BENCH_DONE_STATUSES,
  BENCH_KNOWN_STATUSES,
  BENCH_REJECTED_STATUSES,
  CONFIDENCE_BAND_ORDER,
  type ConfidenceBand,
} from "./reconciliation.generated";
export { KEY_FIELD };

/** The case decorated with a session-local display status (starts at the ledger status,
 *  updates from the writer's response after each decision). */
export type BenchRow = Case & { displayStatus: string };

export type Bucket = "needsReview" | "recommended" | "rejected" | "done";

export type DecideResponse = {
  result: string; // created | existing | superseded | unsure
  assertion: { status?: string } | null;
  same_as: unknown;
};

export const usd = (n: number): string => `$${Math.round(n).toLocaleString("en-US")}`;

/** The vendor org id (context is keyed by this). */
export const vendorId = (c: Case): string => caseRefs(c).vendorId;

/** The proposed identity key (the registry anchor's public key field), or an em-dash. */
export function proposedKey(c: Case): string {
  return caseRefs(c).proposedKey;
}

export function nonActionableReason(_c: Case): string | null {
  return null;
}

/** The best display name: the graph's real label, falling back to the raw vendor ref. */
export function displayName(c: Case, ctx: ContextEntry | undefined): string {
  return ctx?.display_label ?? c.candidate_joins[0].left_ref.display_label;
}

/** Money-in for sorting; -1 when no context so unenriched rows sort to the bottom. */
export function moneyOf(c: Case, ctx: Record<string, ContextEntry>): number {
  return ctx[vendorId(c)]?.money_total ?? -1;
}

const REJECTED = new Set<string>(BENCH_REJECTED_STATUSES);
const DONE = new Set<string>(BENCH_DONE_STATUSES);

/** The ledger statuses the writer can stamp — anything else echoed back is untrusted. */
const KNOWN_STATUSES = new Set<string>(BENCH_KNOWN_STATUSES);

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
  if (nonActionableReason(r)) return false;
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

/** First AI verdict ("same" | "different" | "unsure"), or null when none. */
export function aiVerdictOf(c: Case): string | null {
  return c.ai_reviews[0]?.verdict ?? null;
}

/** AI confidence for sorting; -1 when there's no review (sorts to the bottom). */
export function aiConfidenceOf(c: Case): number {
  return c.ai_reviews[0]?.signal_strength ?? -1;
}

/** Active confidence band; masked/stale/retired records stay hidden from bench controls. */
export function activeConfidenceBand(c: Case): ConfidenceBand | null {
  return c.confidence?.status === "active" ? c.confidence.band : null;
}

const BAND_RANK = new Map<ConfidenceBand, number>(
  CONFIDENCE_BAND_ORDER.map((band, i) => [band, CONFIDENCE_BAND_ORDER.length - i]),
);

export function confidenceBandRank(band: ConfidenceBand | null): number {
  return band ? (BAND_RANK.get(band) ?? 0) : 0;
}

/** Whether the candidate matched on a normalized-exact name (the strong name signal). */
export function isNameExact(c: Case): boolean {
  return (c.candidate_joins[0].signals ?? []).includes("normalized_name_exact");
}

// --- queue controls: filter + sort within the active bucket ------------------

export type SortKey = "money" | "name" | "ai";
export type SortDir = "asc" | "desc";
export type VerdictFilter = "all" | "same" | "different" | "unsure";
export type NameFilter = "all" | "exact" | "fuzzy";
export type BandFilter = "all" | ConfidenceBand;

export type QueueControls = {
  search: string;
  verdict: VerdictFilter;
  nameMatch: NameFilter;
  confidenceBand: BandFilter;
  minMoney: number;
  sortKey: SortKey;
  sortDir: SortDir;
};

export const DEFAULT_CONTROLS: QueueControls = {
  search: "",
  verdict: "all",
  nameMatch: "all",
  confidenceBand: "all",
  minMoney: 0,
  sortKey: "money",
  sortDir: "desc",
};

const haystack = (c: Case, ctx: ContextEntry | undefined): string =>
  [
    displayName(c, ctx),
    c.candidate_joins[0].left_ref.display_label,
    c.candidate_joins[0].right_ref.display_label,
    vendorId(c),
    proposedKey(c),
  ]
    .join(" ")
    .toLowerCase();

/** Filter + sort the active bucket per the operator's controls. Pure; the component owns
 *  the control state and calls this for the displayed list. */
export function applyControls(
  rows: BenchRow[],
  ctx: Record<string, ContextEntry>,
  controls: QueueControls,
): BenchRow[] {
  const q = controls.search.trim().toLowerCase();
  let out = rows;
  if (q.length >= 2) out = out.filter((r) => haystack(r, ctx[vendorId(r)]).includes(q)); // min length avoids "a"/"10" matching everything
  if (controls.verdict !== "all") out = out.filter((r) => aiVerdictOf(r) === controls.verdict);
  if (controls.nameMatch !== "all") out = out.filter((r) => isNameExact(r) === (controls.nameMatch === "exact"));
  if (controls.confidenceBand !== "all") out = out.filter((r) => activeConfidenceBand(r) === controls.confidenceBand);
  if (controls.minMoney > 0) out = out.filter((r) => moneyOf(r, ctx) >= controls.minMoney);

  const sign = controls.sortDir === "asc" ? 1 : -1;
  // Stable, direction-independent tie-break on case_id (intentional — predictable ordering).
  const byId = (a: BenchRow, b: BenchRow) => a.case_id.localeCompare(b.case_id);
  return [...out].sort((a, b) => {
    let d = 0;
    if (controls.sortKey === "name") d = displayName(a, ctx[vendorId(a)]).localeCompare(displayName(b, ctx[vendorId(b)]));
    else if (controls.sortKey === "ai") d = confidenceBandRank(activeConfidenceBand(a)) - confidenceBandRank(activeConfidenceBand(b));
    else d = moneyOf(a, ctx) - moneyOf(b, ctx);
    return sign * d || byId(a, b);
  });
}

// --- investigation deep-links (operator opens these to verify a candidate) --

export type InvestigationLink = { label: string; url: string };

/** External links to investigate a candidate from the bench. Source registries first
 *  (ProPublica for EIN nonprofits, CA SOS bizfile for SOS entities), then a web search.
 *  We don't ingest websites, so search is the substitute. The web search uses the
 *  REGISTRY anchor's org name + city — both public registry fields, and the anchor is an
 *  org by construction (it carries a corporate/EIN id) — never the raw vendor string,
 *  which keeps any natural-person-shaped vendor label out of the outbound query. */
export function investigationLinks(c: Case): InvestigationLink[] {
  const join = c.candidate_joins[0];
  const src = join.left_ref.source_id;
  const orgName = join.right_ref.display_label;
  const city = join.right_ref.public_fields.principal_city;
  const links: InvestigationLink[] = [];

  if (src === "ein") {
    const ein = proposedKey(c).replace(/\D/g, "");
    if (/^\d{9}$/.test(ein)) links.push({ label: "ProPublica 990s", url: `https://projects.propublica.org/nonprofits/organizations/${ein}` });
  } else if (src === "sos_id") {
    links.push({ label: "CA SOS bizfile", url: "https://bizfileonline.sos.ca.gov/search/business" });
  }

  const q = encodeURIComponent([orgName, city].filter(Boolean).join(" "));
  if (q) links.push({ label: "Web search", url: `https://www.google.com/search?q=${q}` });
  return links;
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
