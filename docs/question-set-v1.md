# Question Set V1

Verified: April 13, 2026

This file defines the first real question set for Marin Civic Graph.

It is not a UI spec.

It is the current answer-seeking contract for the graph.

## Why This Exists

The project is now past the stage where more structure alone is useful.

The next risk is widening ingestion without a concrete answer target.

The fix is to keep a small, durable question set that:

- exercises the important joins
- maps to current projected read models
- exposes the next missing data layer when an answer is weak

## Current North-Star Question

### QX-001: Which San Rafael local threads carry the most combined money pressure and legal pressure, and who are the recurring counterparties around them?

Why this is first:

- it matches the current graph density
- it exercises `Decision -> MoneyFlow`, `Program/Project -> Decision`, `Case -> Decision/Program`, and `Record -> evidence`
- it stays close to the real product thesis without overclaiming

Current answer surfaces:

- [San Rafael Local Pressure Comparison](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-comparison.json)
- [San Rafael Local Pressure Explanation](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-explanation.json)

Current answer boundary:

- `6` local threads are now in scope today:
  - `2` program threads
  - `2` project threads
  - `2` QA-backed city-election threads
- the answer now includes `2` legal-pressure-bearing local threads:
  - `program-san-rafael-sanctioned-camping`
  - `program-san-rafael-camping-ordinance-implementation`
- the answer now includes a second money-heavy local project thread with a materially different counterparty pattern:
  - `project-san-rafael-350-merrydale-interim-shelter`
  - this adds county-grant, property-acquisition, brokerage, and project-services pressure that was not visible in the prior comparison

Next ingest trigger:

- widen only when the graph needs either:
  - a second legally constrained local thread with its own direct money path
  - or another materially different local-pressure pattern beyond the current program/project/election mix

## Supporting Questions

### QX-002: Why does this thread rank high?

Answer should show:

- linked money volume
- legal pressure
- decision density
- evidence density
- concentrated counterparties

Current answer surfaces:

- [Sanctioned Camping Local Pressure Summary](../data/projected/graph-v1/views/program-san-rafael-sanctioned-camping-local-pressure-summary.json)
- [San Rafael Local Pressure Explanation](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-explanation.json)

### QX-003: Which local decisions actually moved this thread?

Answer should show:

- meeting
- agenda item
- decision
- vote
- linked money and evidence

Current answer surfaces:

- [Resolution 15336 Decision Dossier](../data/projected/graph-v1/views/decision-2024-08-19-resolution-15336-dossier.json)
- [San Rafael Decision Money Explanation](../data/projected/graph-v1/views/decision-money-san-rafael-explanation.json)

### QX-004: Which organizations, vendors, or institutions recur around this thread?

Answer should show:

- recurring counterparties
- overlap across decisions, filings, programs, or projects
- organization-level context, not just one mention

Current answer surfaces:

- [Downtown Streets Team Organization Dossier](../data/projected/graph-v1/views/organization-downtown-streets-team-dossier.json)
- [Money Overlap Summary](../data/projected/graph-v1/views/money-overlap-summary.json)
- [San Rafael Local Pressure Comparison](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-comparison.json)

### QX-005: What legal constraints bear on this local thread?

Answer should show:

- in-scope cases
- why they are relevant
- linked local decisions and programs
- supporting legal records

Current answer surfaces:

- [Boyd Case Dossier](../data/projected/graph-v1/views/case-boyd-v-city-of-san-rafael-dossier.json)
- [Legal Constraint View](../data/projected/graph-v1/views/legal-constraint-view.json)
- [San Rafael Jurisdiction Legal Constraint Summary](../data/projected/graph-v1/views/jurisdiction-san-rafael-legal-constraint-summary.json)

### QX-006: What in this graph slice still does not reconcile cleanly?

Answer should show:

- validation queue
- subject filing
- delta
- evidence source

Current answer surfaces:

- [Validation Queue](../data/projected/graph-v1/views/validation-queue.json)
- [Graph Query Pack Report](../data/projected/graph-v1/query-pack-report.json)

## Rule For Next Work

Do not widen the graph just because a new source family looks interesting.

Widen only when one of these is true:

- a current question cannot be answered cleanly
- a current answer is too thin to be representative
- a new source would materially improve one of the existing questions

## Current Recommendation

Use `QX-001` as the main driver.

That means the next missing thing is not another abstract domain tranche.

It is whichever bounded local thread most improves the current San Rafael pressure comparison without degrading data quality.
