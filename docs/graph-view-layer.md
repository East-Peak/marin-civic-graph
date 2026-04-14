# Graph View Layer

Verified: April 13, 2026

This is the first product-facing view layer over the projected `graph-v1` payload.

It exists to answer a narrower question than the query pack:

- not just "does the graph pass the gate?"
- but "can the graph now emit dossier-style views a product could actually render?"

## Why This Exists

The project now has enough density that raw bundle counts are no longer the main test.

The next useful pressure test is whether the graph can produce bounded, human-usable views for:

- a recurring officeholder
- a high-signal decision
- money adjacency
- legal constraints
- validation / anomaly review

That is the point of this layer.

## Current Builder

- [build_graph_views.py](../scripts/build_graph_views.py)
- [view-targets.yaml](../registry/view-targets.yaml)
- [graph-read-model-contracts.md](./graph-read-model-contracts.md)

It runs against the projected graph payload:

- [nodes.jsonl](../data/projected/graph-v1/nodes.jsonl)
- [edges.jsonl](../data/projected/graph-v1/edges.jsonl)

And writes:

- [index.json](../data/projected/graph-v1/views/index.json)
- [summary.md](../data/projected/graph-v1/views/summary.md)

## Current Views

### Actor dossier

- [actor-kate-colin-dossier.json](../data/projected/graph-v1/views/actor-kate-colin-dossier.json)
- [actor-rachel-kertz-dossier.json](../data/projected/graph-v1/views/actor-rachel-kertz-dossier.json)

Current scope:

- canonical actor
- seat-service continuity
- committees and filings
- council vote history
- connected money flows
- linked evidence records

### Decision dossier

- [decision-2024-08-19-resolution-15336-dossier.json](../data/projected/graph-v1/views/decision-2024-08-19-resolution-15336-dossier.json)

Current scope:

- decision
- meeting
- agenda item
- votes
- evidence records
- linked money flows
- linked cases and programs

### Money overlap summary

- [money-overlap-summary.json](../data/projected/graph-v1/views/money-overlap-summary.json)

Current scope:

- overall `MoneyFlow` type counts
- top connected non-record / non-filing subjects
- overlap subjects that recur across multiple money flows

### Legal constraint view

- [legal-constraint-view.json](../data/projected/graph-v1/views/legal-constraint-view.json)

Current scope:

- case summaries
- proceedings
- participations
- legal records
- shared issues / programs
- linked local San Rafael decisions

### Validation queue

- [validation-queue.json](../data/projected/graph-v1/views/validation-queue.json)

Current scope:

- `ValidationCheck` status / severity queue
- linked filing subject
- derived record
- delta-focused ordering

### Organization dossier

- [organization-downtown-streets-team-dossier.json](../data/projected/graph-v1/views/organization-downtown-streets-team-dossier.json)

### Case dossier

- [case-boyd-v-city-of-san-rafael-dossier.json](../data/projected/graph-v1/views/case-boyd-v-city-of-san-rafael-dossier.json)

### Program dossier

- [program-san-rafael-sanctioned-camping-dossier.json](../data/projected/graph-v1/views/program-san-rafael-sanctioned-camping-dossier.json)
- [program-san-rafael-camping-ordinance-implementation-dossier.json](../data/projected/graph-v1/views/program-san-rafael-camping-ordinance-implementation-dossier.json)
- [program-csl-building-forward-dossier.json](../data/projected/graph-v1/views/program-csl-building-forward-dossier.json)

Current scope:

- program
- operating institution
- jurisdiction
- evidence records and related records
- linked decisions, cases, and money flows

### Project dossier

- [project-downtown-library-renovation-dossier.json](../data/projected/graph-v1/views/project-downtown-library-renovation-dossier.json)

Current scope:

- project
- primary place and jurisdiction
- evidence records and related records
- linked programs and decisions
- agreements and amendments
- linked money flows

### Jurisdiction delivery summary

- [jurisdiction-san-rafael-delivery-summary.json](../data/projected/graph-v1/views/jurisdiction-san-rafael-delivery-summary.json)

Current scope:

- one jurisdictional place
- program and project rollups
- linked decisions
- linked money flows
- linked cases
- evidence and related records

### Decision money rollup

- [decision-money-san-rafael-rollup.json](../data/projected/graph-v1/views/decision-money-san-rafael-rollup.json)

Current scope:

- one jurisdictional place
- money-linked decisions ranked by linked amount
- meeting and agenda-item context
- linked programs, projects, and cases
- linked money flows and evidence records

### Decision money explanation

- [decision-money-san-rafael-explanation.json](../data/projected/graph-v1/views/decision-money-san-rafael-explanation.json)

Current scope:

- one jurisdictional place
- explained money-linked decisions
- flow-type breakdowns
- counterparties and agreement/program/project context
- linked money flows with evidence records

### Program local pressure summary

- [program-san-rafael-sanctioned-camping-local-pressure-summary.json](../data/projected/graph-v1/views/program-san-rafael-sanctioned-camping-local-pressure-summary.json)
- [program-san-rafael-camping-ordinance-implementation-local-pressure-summary.json](../data/projected/graph-v1/views/program-san-rafael-camping-ordinance-implementation-local-pressure-summary.json)

Current scope:

- one local program thread
- supporting local decisions plus any money-linked decision explanations that fall inside that decision set
- linked legal case rollups
- shared issue pressure across the in-scope case set
- top counterparties and supporting evidence records

### Jurisdiction local pressure comparison

- [jurisdiction-san-rafael-local-pressure-comparison.json](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-comparison.json)

Current scope:

- one jurisdictional place
- side-by-side rollups for in-scope program, project, and bounded election threads
- per-thread money pressure, legal pressure, and evidence density
- overall top counterparties across those threads
- bounded comparison over the current graph, not new ingest

### Jurisdiction local pressure explanation

- [jurisdiction-san-rafael-local-pressure-explanation.json](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-explanation.json)

Current scope:

- one jurisdictional place
- ranked explanations for each in-scope thread
- explicit ranking method
- pairwise deltas between the top-ranked threads
- bounded explanation over the current comparison layer, not new ingest

### Jurisdiction legal constraint summary

- [jurisdiction-san-rafael-legal-constraint-summary.json](../data/projected/graph-v1/views/jurisdiction-san-rafael-legal-constraint-summary.json)

Current scope:

- one jurisdictional place
- in-scope program and project context
- legal case rollups filtered to the jurisdiction
- linked local decisions and shared issues
- case-lineage links across the in-scope legal set
- evidence and related records

## Use

Run:

```bash
python3 scripts/build_graph_views.py
python3 scripts/serve_graph_views.py
```

Then open:

```text
http://127.0.0.1:8017/viewer/
```

## Boundary

This is not a real frontend or a graph API.

It is a product-facing view pack over the projected graph so we can:

- validate the current graph shape
- spot weak joins earlier
- decide what a real UI should ask for
- avoid widening ingestion without a concrete product question

The local shell is intentionally static and read-only:

- it serves files from the repo root
- it reads the generated JSON view pack under `data/projected/graph-v1/views/`
- it does not talk to Neo4j
- it does not introduce another app stack before the product questions are clearer
