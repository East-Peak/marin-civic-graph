# Controlled Breadth Sprint Proposal

Verified: April 12, 2026

This proposal defines the next project phase.

The goal is to widen coverage across source families that already have working adapters and stable graph objects, without widening the ontology again.

## Why This Phase

The project is no longer blocked on basic architecture.

It now has:

- stable IDs and explicit join rules
- a working projection layer and live Neo4j load
- durable normalized bundles across meetings, campaign finance, disclosures, legal, permits, procurement, and media
- a repo-local and workspace-level decision trail

The new risk is not missing ontology. The new risk is fragmentation:

- too many good slices
- not enough density across the same source families
- not enough repeated actors, committees, records, and decisions to test the real graph product

So the next move should be breadth across the existing backbone, not another tranche of model invention.

## Phase Rule

During this sprint:

- freeze schema by default
- avoid new domain tranches
- prefer more data over more modeling

A new node type is only justified if:

1. a real source cannot be represented cleanly without it
2. a real query cannot be answered without it
3. the same object boundary appears in multiple source families

## Objective

Build enough repeated coverage across the existing San Rafael and Marin County backbone that graph-v1 can answer recurring-actor, recurring-money, recurring-decision, and validation questions without leaning on one-off worked examples.

## In Scope

### Track A: San Rafael City Council `2019+`

Goal:

- complete the meeting spine from `2019-01-01` forward
- keep packet / minutes / agenda / video availability explicit

Expected yield:

- `Meeting`
- `AgendaItem`
- `Decision`
- `VoteCast`
- `Record`

Why:

- strongest city-side decision backbone
- best place to densify decisions, records, and future recurring actors

### Track B: Marin County Board of Supervisors `2019+`

Goal:

- complete the county meeting spine from `2019-01-01` forward

Expected yield:

- `Meeting`
- `AgendaItem`
- `Decision`
- `VoteCast`
- `Record`

Why:

- county-side equivalent of the city backbone

### Track C: Marin County Campaign Finance `2019+`

Goal:

- operationalize yearly exports plus current change feed

Expected yield:

- `Committee`
- `Filing`
- `MoneyFlow`
- `Election`
- `Candidacy`

Why:

- strong official surface
- high recurring-actor value

### Track D: San Rafael City-Side Campaign Filings `2019+`

Goal:

- move from selected high-value filings to broader cycle coverage
- keep discovery, folder listing, OCR, and PDF export paths separate but coordinated

Expected yield:

- `Committee`
- `Filing`
- `MoneyFlow`
- `Candidacy`
- `Record`
- `ValidationCheck`

Why:

- this is the strongest path to true local media-to-campaign and local decision-to-finance overlap

### Track E: San Rafael Form `700` and Form `803`

Goal:

- backfill visible Form `700` inventory from `2019-01-01`
- census all visible local Form `803` records and keep the low-volume path current

Expected yield:

- `EconomicInterestDisclosure`
- `Filing`
- `MoneyFlow: behested_payment`
- `Actor`
- `Seat`
- `SeatService`

Why:

- clean officeholder continuity layer
- joins directly into elected structure already in graph-v1

## Out Of Scope

Do not widen into these during the breadth sprint unless a source directly forces it:

- new legal case families beyond the current `Boyd` + `Grants Pass` pair
- criminal-case expansion
- broader permit backfill
- broader procurement backfill
- new media methodology
- new jurisdictions
- new major node families

These are valid later targets. They are not the current bottleneck.

## Execution Shape

### Step 1: Coverage First

For each in-scope track:

- capture or complete historical inventory
- normalize into durable bundles
- add to projection/import only when the objects are stable

### Step 2: Query Benchmarks

At the end of each track checkpoint, rerun a fixed query set:

- actor dossier
- decision dossier
- committee / donor recurrence
- officeholder disclosure continuity
- validation / unreconciled filing queue

The graph should get denser, not just bigger.

### Step 3: Import Scope Gate

Do not automatically widen graph-v1 import scope just because a new bundle exists.

Each new bundle family must answer:

- is it durable
- is it repeated enough to matter
- does it improve the fixed query set

## Deliverables

Minimum deliverables for the sprint:

- complete or materially deepen the `2019+` inventory for all five in-scope tracks
- promote that coverage into normalized bundles, not just raw captures
- keep graph-v1 projection and smoke checks passing
- produce one before/after query pack showing how recurrence improved

## Success Criteria

This sprint is successful if the graph can answer these with density rather than one-off examples:

- show all records, filings, officeholding, and disclosure continuity tied to one officeholder
- show recurring committees, donors, and outside-spending records across cycles
- show recurring actors and orgs across meetings, records, and money
- show validation failures and partially reconciled filing objects
- show decision continuity over time rather than one isolated case study

## Failure Modes To Watch

- too much new schema
- too many new domains
- too much time spent on one stubborn adapter edge case
- widening import scope before bundle quality is stable
- confusing “more files” with “more graph value”

## Recommended Next Slice

Start with a narrow planning and review checkpoint, then execute in this order:

1. San Rafael City Council `2019+`
2. Marin County BOS `2019+`
3. Marin County campaign finance `2019+`
4. San Rafael Form `700` / `803`
5. San Rafael city-side campaign filings `2019+`

Reason:

- decision spines first
- then county money
- then officeholder disclosure continuity
- then the more brittle city-side campaign surfaces

## Decision Gate After Sprint

After the breadth sprint, decide one of:

- widen graph-v1 import to include the legal pair
- widen graph-v1 import to include one procurement thread
- widen graph-v1 import to include one permit thread

That decision should follow observed query value, not instinct.
