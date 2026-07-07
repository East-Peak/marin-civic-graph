// AUTO-GENERATED from registry/reconciliation.json - DO NOT EDIT BY HAND.
// Regenerate: node app/scripts/codegen-reconciliation.mjs
// The registry is the single source of truth for reconciliation status/key-source mechanics.

export const LEDGER_ACTIONABILITY = {
  "none": "actionable",
  "requeued": "needs_review",
  "approved": "resolved",
  "deterministic": "resolved",
  "superseded": "resolved",
  "rejected_current_evidence": "resolved",
  "rejected_entity_distinct": "resolved",
} as const;

export type LedgerStatus = keyof typeof LEDGER_ACTIONABILITY;
export type LedgerActionability = (typeof LEDGER_ACTIONABILITY)[LedgerStatus];

export const BENCH_REJECTED_STATUSES = [
  "rejected_current_evidence",
  "rejected_entity_distinct",
] as const;

export const BENCH_DONE_STATUSES = [
  "approved",
  "superseded",
  "deterministic",
  "unsure",
] as const;

export const BENCH_KNOWN_STATUSES = [
  "none",
  "requeued",
  "approved",
  "superseded",
  "deterministic",
  "rejected_current_evidence",
  "rejected_entity_distinct",
] as const;

export const CONFIDENCE_BAND_ORDER = [
  "high",
  "medium",
  "low",
] as const;

export const CONFIDENCE_BAND_THRESHOLDS = {
  "high_min_confidence": 0.8,
  "medium_min_confidence": 0.65,
  "high_min_dimensions": 2,
} as const;

export const KEY_SOURCE_SPECS = {
  "ein": {
    source_id: "ein",
    public_key_field: "registry_ein",
    anchor_prefix: "org-bmf-ein-",
    anchor_source: "irs_bmf",
    attach_basis: "operator_approved_ein",
    anchor_subject_fields: {
      "display_label": "vendor_ref.display_label|anchor_id",
      "ein": "candidate.ein|anchor_suffix",
      "source": "const:irs_bmf",
    },
  },
  "sos_id": {
    source_id: "sos_id",
    public_key_field: "sos_id",
    anchor_prefix: "org-casos-",
    anchor_source: "ca_sos",
    attach_basis: "operator_approved_sos_id",
    anchor_subject_fields: {
      "display_label": "candidate.sos_ref.display_label|anchor_id",
      "sos_id": "candidate.sos_ref.sos_id",
      "source": "const:ca_sos",
    },
  },
  "committee_id": {
    source_id: "committee_id",
    public_key_field: "committee_id",
    anchor_prefix: "org-fppc-",
    anchor_source: "fppc",
    attach_basis: "operator_approved_committee_id",
    anchor_subject_fields: {
      "display_label": "vendor_ref.display_label|anchor_id",
      "committee_id": "candidate.committee_id",
      "entity_class": "const:committee",
      "source": "const:fppc",
    },
  },
} as const;

export const KEY_FIELD_BY_SOURCE: Record<string, string> = {
  "ein": "registry_ein",
  "sos_id": "sos_id",
  "committee_id": "committee_id",
};
