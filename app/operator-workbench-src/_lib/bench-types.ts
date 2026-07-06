// Shared read-model case types for the Identity Attach Workbench bench (Slice 3).
// React-free and server-free so both the server page and the client component (and the
// TDD'd bench-logic) can share one contract. Mirrors the JSONL the Goal-1 emitter +
// reconciliation_overlay produce (see scripts/reconciliation_read_model.py).
//
// ContextEntry is re-exported type-only from operator-context (the value module pulls in
// the Neo4j driver, which is server-only — a type re-export is erased and stays safe in
// the browser bundle and in vitest).
export type { ContextEntry } from "./operator-context";

export type Ref = {
  source_id: string;
  local_id: string;
  display_label: string;
  public_fields: Record<string, unknown>;
};

export type Join = {
  left_ref: Ref; // the County vendor org
  right_ref: Ref; // the registry key-anchor (IRS BMF / CA-SOS)
  signals: string[];
  signal_strength: number;
};

export type AiReview = {
  verdict: string; // "same" | "different" | "uncertain" (advisory only)
  reason?: string;
  signal_strength: number;
};

export type Case = {
  case_id: string;
  candidate_joins: Join[];
  ai_reviews: AiReview[];
  current_ledger_status: string;
  bulk_eligible: boolean;
  review_flags: Record<string, boolean>;
};
