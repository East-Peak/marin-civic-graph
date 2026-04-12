# Reconciliation And Anomaly Model

Verified: April 12, 2026

This note defines how the project should distinguish:

- parser failure
- source inconsistency
- real anomaly worth investigating

That distinction is non-negotiable. Without it, the graph will confuse extraction bugs with filing irregularities.

## Core Rule

Do not jump from a mismatch directly to an accusation.

The graph should move in this order:

1. preserve the source record
2. extract structured values
3. emit explicit validation checks
4. classify the mismatch
5. only then build higher-order anomaly views

## ValidationCheck

Use `ValidationCheck` as the generic graph object for machine-verifiable QA.

Examples:

- extracted itemized contributions versus the official `Schedule A Summary`
- extracted itemized payments versus the official `Schedule E Summary`
- summary rollup arithmetic versus the reported total on the same filing
- later cross-source amount checks between a staff report, resolution, and contract

Recommended fields:

- `id`
- `check_type`
- `subject_node_id`
- `subject_node_type`
- `metric_name`
- `measured_value_number?`
- `measured_value_label?`
- `reference_value_number?`
- `reference_value_label?`
- `delta_value_number?`
- `absolute_delta_value_number?`
- `delta_direction?`
- `status`
- `severity`
- `confidence`
- `derived_from_record_id`
- `derived_from_segment_id?`
- `evidence_record_ids[]`

### Check Types

- `reconciliation_check`
  Compare extracted or computed values against an official reference value.
- `summary_consistency_check`
  Check whether a source’s own summary lines add up internally.
- `cross_source_consistency_check`
  Compare the same amount or fact across multiple official records.
- `coverage_check`
  Record that a source family is only partially recoverable or only partly extracted.

### Recommended Status Values

- `reconciled`
- `partially_reconciled`
- `extraction_gap`
- `source_inconsistency`
- `needs_review`

## Anomaly Layer

Do not make `AnomalyFlag` a first-class primitive yet.

For now, anomaly views should be derived from:

- repeated `ValidationCheck` failures
- repeated actor / vendor / committee recurrence
- cross-domain joins like campaign money plus contracts plus decisions

Examples:

- one filing with a bounded extraction gap is not an anomaly
- the same committee repeatedly funding actors adjacent to related city contracts is anomaly-worthy context
- a filing whose own summary lines do not add up is stronger than a parser miss

## First Live Use: San Rafael Form 460

The first live implementation is the selected San Rafael city-side `Form 460` slice.

That slice now emits two validation families per filing:

- `reconciliation_check`
  - `schedule_a_itemized_contributions`
  - `schedule_e_itemized_payments`
- `summary_consistency_check`
  - `schedule_a_total_contributions_rollup`
  - `schedule_e_total_payments_rollup`

This is the right shape because it separates:

- extraction trailing the official itemized subtotal
- official summary lines failing to add up on their own

Those are different failure modes and should stay different in the graph.

## Interpretation Rule

Use `ValidationCheck` for:

- QA dashboards
- source-family health
- reconciliation status on filings, contracts, and determinations
- later anomaly triage

Do not use `ValidationCheck` alone for:

- fraud claims
- kickback claims
- public misconduct claims

Those require cross-record evidence, not just a failed check.
