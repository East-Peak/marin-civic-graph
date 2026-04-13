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
