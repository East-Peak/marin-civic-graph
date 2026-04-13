# Graph Read-Model Contracts

Verified: April 13, 2026

This file defines the JSON output contracts for product-facing projected graph views.

These are read models, not source truth.

Source truth still lives in:

- `data/raw/`
- `data/extracted/`
- `data/normalized/`
- `data/projected/graph-v1/`

## Why This Exists

The project now has enough graph density that the next risk is not missing ontology.

It is drift between:

- what the graph stores
- what product-shaped consumers actually need
- what later frontend work expects

The fix is to define stable JSON contracts over the projected graph.

## Control File

View generation is now target-driven.

- [view-targets.yaml](../registry/view-targets.yaml)

That manifest decides which dossiers and summaries are generated.

## Shared Envelope

Every generated view should carry:

- `id`
- `title`
- `view_type`
- `contract_version`
- `generated_at`

Subject-specific dossiers should also carry:

- `subject_id`
- `subject_node_type`

## Current View Types

### `actor_dossier`

Subject:

- one canonical `Actor`

Current shape:

- `actor`
- `metrics`
- `seat_services`
- `committees`
- `candidacies`
- `filings`
- `council_votes`
- `money_flows`
- `evidence_records`
- `related_records`

### `organization_dossier`

Subject:

- one canonical organizational `Actor`

Current shape:

- `organization`
- `metrics`
- `money_flows`
- `linked_decisions`
- `evidence_records`
- `related_records`
- `linked_cases`
- `linked_programs`

### `decision_dossier`

Subject:

- one `Decision`

Current shape:

- `decision`
- `meeting`
- `agenda_items`
- `metrics`
- `votes`
- `evidence_records`
- `linked_money_flows`
- `linked_cases`
- `linked_programs`

### `case_dossier`

Subject:

- one `Case`

Current shape:

- `case`
- `court`
- `metrics`
- `proceedings`
- `participations`
- `evidence_records`
- `related_records`
- `issues`
- `programs`
- `places`
- `linked_local_decisions`

### `program_dossier`

Subject:

- one `Program`

Current shape:

- `program`
- `institution`
- `jurisdiction_place`
- `metrics`
- `places`
- `evidence_records`
- `related_records`
- `linked_cases`
- `linked_decisions`
- `linked_money_flows`

Current note:

- `linked_money_flows` may be sourced either from direct `MoneyFlow -> Program` links or from `MoneyFlow -> Decision -> Program` paths when the normalized bundle only encodes the decision crosswalk.

### `project_dossier`

Subject:

- one `Project`

Current shape:

- `project`
- `primary_place`
- `jurisdiction_place`
- `metrics`
- `evidence_records`
- `related_records`
- `linked_programs`
- `linked_decisions`
- `agreements`
- `amendments`
- `linked_money_flows`

Current note:

- `linked_money_flows` may be sourced either from direct `MoneyFlow -> Project` links or from `MoneyFlow -> Decision -> Project` paths when the normalized bundle only encodes the decision crosswalk.

### `jurisdiction_delivery_summary`

Subject:

- one jurisdictional `Place`

Current shape:

- `jurisdiction_place`
- `metrics`
- `program_rollups`
- `project_rollups`
- `linked_decisions`
- `linked_money_flows`
- `linked_cases`
- `evidence_records`
- `related_records`

Current note:

- this is a bounded read-model rollup over the existing `program_dossier` and `project_dossier` layer
- it does not create new graph truth edges
- it is meant to answer a broader product question: what active program/project delivery threads, decisions, money, and constraint context currently exist within one jurisdiction

### `decision_money_rollup`

Subject:

- one jurisdictional `Place`

Current shape:

- `jurisdiction_place`
- `metrics`
- `decision_rollups`

Each rollup currently includes:

- `decision`
- `meeting`
- `agenda_items`
- `metrics`
- `linked_programs`
- `linked_projects`
- `linked_cases`
- `linked_money_flows`
- `evidence_records`

Current note:

- this is a bounded read model over existing `Decision -> MoneyFlow`, `Decision -> Project`, `Program -> Decision`, and `Case -> Decision` graph paths
- it is intended to answer: which local decisions are currently driving the most linked money, and what program/project/case context travels with them

### `decision_money_explanation`

Subject:

- one jurisdictional `Place`

Current shape:

- `jurisdiction_place`
- `metrics`
- `decision_explanations`

Each explanation currently includes:

- `decision`
- `meeting`
- `agenda_items`
- `metrics`
- `flow_breakdown`
- `counterparties`
- `linked_programs`
- `linked_projects`
- `linked_cases`
- `linked_money_flows`
- `evidence_records`
- `explanation_flags`

Current note:

- this is a richer explanatory layer over the existing `decision_money_rollup`
- it is intended to answer not just which decisions rank high, but why they do: by showing flow-type mix, counterparties, and agreement/program/project/case context

### `program_local_pressure_summary`

Subject:

- one `Program`

Current shape:

- `program`
- `institution`
- `jurisdiction_place`
- `places`
- `metrics`
- `decision_explanations`
- `legal_case_rollups`
- `top_counterparties`
- `evidence_records`

Current note:

- this is a bounded synthesis layer over the existing `program_dossier`, `decision_money_explanation`, and `case_dossier` read models
- it is intended to answer one local-thread question: how legal pressure, local decisions, and linked money concentrate around a specific program without inventing new graph truth edges
- linked money remains decision-derived here unless a direct `MoneyFlow -> Program` path already exists in the imported graph

### `jurisdiction_local_pressure_comparison`

Subject:

- one jurisdictional `Place`

Current shape:

- `jurisdiction_place`
- `metrics`
- `thread_rollups`
- `top_counterparties`
- `evidence_records`

Each thread rollup currently includes:

- `thread_type`
- `subject`
- `context`
- `metrics`
- `pressure_flags`
- `linked_decisions`
- `linked_cases`
- `top_counterparties`

Current note:

- this is a bounded comparison layer over the current in-scope program and project threads for one jurisdiction
- it is intended to answer a harder product question than a single dossier: which local delivery threads currently carry the most combined money pressure, legal pressure, and evidence density
- it still derives pressure from existing read models and graph paths; it does not mint new graph truth edges

### `jurisdiction_legal_constraint_summary`

Subject:

- one jurisdictional `Place`

Current shape:

- `jurisdiction_place`
- `metrics`
- `programs_in_scope`
- `projects_in_scope`
- `case_rollups`
- `case_lineage`
- `evidence_records`
- `related_records`

Each case rollup currently includes:

- `case`
- `court`
- `metrics`
- `scope_hits`
- `issues`
- `programs`
- `linked_local_decisions`
- `records`

Current note:

- this is a bounded read model over the imported legal lane plus local San Rafael program and decision links
- it is intended to answer: which legal constraint cases currently touch this jurisdiction, why they are in scope, and how they overlap on local programs and decisions

### `money_overlap_summary`

Current shape:

- `metrics`
- `top_overlap_subjects`

### `legal_constraint_view`

Current shape:

- `metrics`
- `case_views`

### `validation_queue`

Current shape:

- `metrics`
- `items`

## Boundary

These contracts are intentionally projected and lossy.

They should:

- be stable enough for product work
- be cheap to regenerate
- stay readable in git

They should not:

- replace normalized bundles
- expose every internal graph edge by default
- become a second schema layer with its own ontology drift
