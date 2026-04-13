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

It runs against the projected graph payload:

- [nodes.jsonl](../data/projected/graph-v1/nodes.jsonl)
- [edges.jsonl](../data/projected/graph-v1/edges.jsonl)

And writes:

- [index.json](../data/projected/graph-v1/views/index.json)
- [summary.md](../data/projected/graph-v1/views/summary.md)

## Current Views

### Actor dossier

- [actor-kate-colin-dossier.json](../data/projected/graph-v1/views/actor-kate-colin-dossier.json)

Current scope:

- canonical actor
- seat-service continuity
- committees and filings
- council vote history
- connected money flows
- linked evidence records

### Decision dossier

- [decision-resolution-15336-dossier.json](../data/projected/graph-v1/views/decision-resolution-15336-dossier.json)

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
