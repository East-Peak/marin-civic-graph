# Graph Materialization Proposal

Verified: April 12, 2026

This proposal turns the current planning repo and normalized bundles into a first real graph product.

The immediate goal is not "all data in Neo4j." The goal is a bounded, queryable v1 that proves the joins and gives the project a usable product surface.

## Why Now

The project has enough core pieces already:

- stable IDs and explicit join rules
- canonical San Rafael seeds
- election / seat / officeholding structure
- campaign, disclosure, and Form 460 slices
- case study 01 with official and media joins
- first validation and reconciliation layer

What is missing is the materialization step. Right now the graph mostly exists as normalized JSON bundles rather than one queryable system.

## Current Readiness

The current bundles already support a narrow but real first import.

Strong existing import candidates:

- [canonical-seeds-san-rafael-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/canonical-seeds-san-rafael-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-election-records-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-discovery-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-ie-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/campaign-finance-form-803-slice-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/bundle-01.json)
- [marin-ij-2024-08-24-mention-claim-example.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/marin-ij-2024-08-24-mention-claim-example.json)
- [marin-ij-recurrence-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/marin-ij-recurrence-example-01.json)
- [media-cross-domain-join-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/media-cross-domain-join-example-01.json)
- [media-disclosure-overlap-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/media-disclosure-overlap-example-01.json)
- [media-campaign-overlap-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/media-campaign-overlap-example-01.json)

These are enough to stand up a first graph centered on:

- San Rafael elected structure
- campaign and disclosure continuity
- the homelessness / Mahon Creek thread
- media-to-official cross-domain joins

## Proposed Architecture

```text
registry/import-manifest.yaml
        |
        v
data/normalized/*.json
        |
        v
scripts/load_neo4j_v1.py
        |
        +--> node upsert pass
        +--> relationship materialization pass
        +--> validation/report pass
        |
        v
Neo4j
        |
        v
query layer / product pages
```

### Import Rules

The importer should be boring.

It should:

- trust normalized bundle IDs
- never re-parse raw HTML or PDFs
- never run LLM logic
- never invent new IDs during import unless the manifest explicitly says to materialize a convenience node

It should:

- upsert nodes by stable `id`
- attach bundle provenance
- materialize explicit relationships from ID refs
- preserve `status`, `confidence`, and review-layer boundaries

## Node Groups For V1

### Canonical

- `Actor`
- `Institution`
- `Seat`
- `SeatService`
- `Election`
- `Committee`
- `Place`
- `Issue`
- `Program`
- `Case`

### Process

- `Meeting`
- `AgendaItem`
- `Decision`
- `Candidacy`
- `Filing`
- `EconomicInterestDisclosure`
- `MoneyFlow`

### Evidence

- `Record`
- `RecordSegment`

### Review

- `Mention`
- `Claim`
- `ValidationCheck`

## Promotion Boundary

This is the main architecture risk.

The repo contains both:

- canonical or strongly promoted objects
- candidate or review-stage objects

The importer must not flatten those together.

Recommended rule:

- every imported node gets `promotion_state`
- allowed values:
  - `canonical`
  - `promoted`
  - `candidate`
  - `review`

Examples:

- canonical seeds import as `canonical`
- filing or meeting objects import as `promoted` when the bundle treats them as durable objects
- `Mention`, `Claim`, and `ValidationCheck` import as `review`

That keeps the graph honest and lets the product filter or expose review material intentionally.

## Proposed Product Tabs

I would not make "the graph" itself a top-level tab.

The product should lead with legible investigative surfaces, and the graph should power them underneath.

### 1. `Investigate`

The landing surface.

Use for:

- global search
- quick question entry
- recent decisions
- hot actors / orgs / issues

### 2. `Actors`

People and organizations.

Use for:

- elected officials
- nonprofits
- vendors
- PACs
- recurring commenters

Each actor page should expose:

- offices or roles
- related records
- money
- meetings / comments
- legal involvement where relevant

### 3. `Decisions`

The core civic-process view.

Use for:

- ordinances
- resolutions
- contract approvals
- permit outcomes
- policy changes

Each decision page should expose:

- the meeting / agenda item
- supporting records
- votes
- related money
- affected places / programs
- legal context if relevant

### 4. `Money`

All financial adjacency in one place.

Use for:

- campaign money
- independent expenditures
- behested payments
- grants
- contracts

This is where donor / vendor / sponsor recurrence becomes visible.

### 5. `Legal`

This needs to be explicit.

The legal / precedent work exists in planning and raw captures, but it is not legible enough in the current normalized surface.

Use for:

- cases
- injunctions
- dismissals
- appellate opinions
- precedent links
- civil grand jury and oversight findings

This tab should answer:

- what constrained the city
- what precedent mattered
- what the city said the precedent meant
- what the court or oversight body actually did

### 6. `Records`

The evidence index.

Use for:

- minutes
- packets
- resolutions
- filings
- articles
- legal records

This is where an evidence-first user can work directly from sources instead of summaries.

## Legal / Precedent Gap

Your observation is correct.

The repo already has legal planning and raw captures:

- [judicial-and-oversight-extension.md](/Users/tammypais/projects/marin-civic-graph/docs/judicial-and-oversight-extension.md)
- [judicial-pressure-test-basket-source-bundle.md](/Users/tammypais/projects/marin-civic-graph/docs/judicial-pressure-test-basket-source-bundle.md)
- [judicial-pressure-test-basket-ingestion-checklist.md](/Users/tammypais/projects/marin-civic-graph/docs/judicial-pressure-test-basket-ingestion-checklist.md)
- [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/scotus-grants-pass-docket/2026-04-10/source.html)
- [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/sf-city-attorney-coalition-injunction-appeal/2026-04-10/source.html)
- [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-grants-pass-statement/2026-04-10/source.html)
- [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-boyd-dismissal-news-release/2026-04-10/source.html)

But it does **not** yet have a clearly named normalized legal bundle the way campaign, disclosure, permit, and procurement do.

That means the legal layer exists conceptually, but not yet as a first-class import surface.

### Proposal

Make `legal-precedent-01` the next normalized bundle after the import skeleton exists.

Minimum scope:

- `case-boyd-v-city-of-san-rafael`
- `case-city-of-grants-pass-v-johnson`
- case participation where public and named
- official legal-framing records already in case study 01
- precedent / local-constraint claims preserved explicitly as `Claim`

That is enough to justify the `Legal` tab early without pretending the entire judicial model is done.

## First Import Scope

Do not import every bundle on day one.

Start with the San Rafael governance spine:

1. canonical seeds
2. election records
3. city campaign discovery / filings / IE / Form 460
4. Form 803
5. homelessness case study bundle and media overlap examples

Defer for phase two:

- permit basket
- procurement basket
- criminal sample basket
- broader legal/oversight bundle beyond the first named precedent set

## Main Risks

### Risk 1: Candidate pollution

If `candidate` and `review` objects are imported without a boundary, the graph will overstate certainty.

Mitigation:

- import `promotion_state`
- default most product views to `canonical` plus `promoted`
- make `review` visible only in explicit audit views

### Risk 2: Duplicate semantics across bundles

The same actor or record can appear in several bundles.

Mitigation:

- manifest ordering
- `MERGE` by stable ID only
- no importer-side fuzzy resolution

### Risk 3: Legal layer invisibility

The legal work is present but easy to miss because it has not been normalized as its own family yet.

Mitigation:

- give `Legal` a top-level product tab
- create `legal-precedent-01` early

### Risk 4: Overbuilding the importer

If the importer tries to solve extraction, validation, and identity resolution, it will become brittle.

Mitigation:

- importer only materializes normalized bundles
- extraction stays in extraction scripts
- identity resolution stays in the normalized layer and seed bundles

## Adversarial Review Questions

- Are `Decisions` and `Records` both needed as top-level tabs, or should one collapse into the other?
- Should `ValidationCheck` live in Neo4j, or should it stay in a sidecar QA store until the product needs it directly?
- Is the `Legal` tab premature before `legal-precedent-01` exists?
- Are we importing too much review-layer material for v1?
- Should permits and procurement stay out of the first import, or are we leaving too much value on the table?

## Recommended Next Commit

If this proposal survives review, the next implementation tranche should be:

- `registry/import-manifest.yaml`
- `scripts/load_neo4j_v1.py`
- one import of the San Rafael governance spine
- one query note showing 3 to 5 real graph traversals
