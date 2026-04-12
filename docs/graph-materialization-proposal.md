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
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-ie-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/campaign-finance-form-803-slice-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/bundle-01.json)
- [aug-19-item-5a-record-splits.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/aug-19-item-5a-record-splits.json)

These are enough to stand up a first graph centered on:

- San Rafael elected structure
- campaign and disclosure continuity
- the homelessness / Mahon Creek thread
- meeting, decision, and filing continuity

## Proposed Architecture

```text
registry/import-manifest.yaml
        |
        v
data/normalized/*.json
        |
        v
scripts/build_graph_projection.py
        |
        +--> normalized node envelope
        +--> normalized edge envelope
        +--> import report
        |
        v
scripts/load_neo4j_v1.py
        |
        +--> node upsert pass
        +--> relationship materialization pass
        |
        v
Neo4j
        |
        v
query layer / product pages
```

### Projection Layer

The projection layer is mandatory.

The current normalized family is not one stable import contract:

- some files are durable bundles
- some are discovery-stage bundles
- some are worked examples
- some contain review-only or candidate-only material that should not land in v1

`build_graph_projection.py` should handle that narrowing before Neo4j sees anything.

It should:

- select importable objects only
- normalize bundle-local field names into one import envelope
- attach `source_bundle_id`
- attach `promotion_state`
- emit flat node and edge payloads
- produce an import report with skipped object counts and reasons

### Import Rules

The importer should be boring.

It should:

- trust the projection output, not bundle-local structure directly
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
  - `review`

Examples:

- canonical seeds import as `canonical`
- filing or meeting objects import as `promoted` when the bundle treats them as durable objects
- `ValidationCheck` imports as `review`

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

Do not ship `Legal & Precedent` or `Records` as top-level tabs in v1.

Reason:

- `Records` is still an evidence mode inside investigation, not a distinct top-level question
- the legal / precedent lane is architecturally important but should stay out of core import until the first normalized legal bundle is stronger than one local case plus follow-on gaps

Instead:

- keep a source / record mode inside `Investigate`
- expose legal / precedent context as sections on actor and decision pages
- promote `Legal & Precedent` to a top-level tab only after `legal-precedent-01` matures beyond the current Boyd-only slice

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

It now has a clearly named normalized legal bundle:

- [legal-precedent-01.md](/Users/tammypais/projects/marin-civic-graph/docs/legal-precedent-01.md)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/legal-precedent-01/bundle-01.json)

But it is still not yet a first-class import surface.

The current bundle proves the local legal lane with:

- `case-boyd-v-city-of-san-rafael`
- one direct court-origin dismissal order
- normalized `Proceeding` and `CaseParticipation` objects
- explicit crosswalks back to the August 19, 2024 San Rafael decision chain

The current remaining gap is also explicit:

- the operative Boyd TRO and preliminary-injunction orders are still not captured directly

### Proposal

Treat `legal-precedent-01` as the first real legal normalization slice, but keep it outside core v1 import until the direct-order coverage is stronger.

Minimum scope:

- `case-boyd-v-city-of-san-rafael`
- one direct court-origin Boyd order
- case participation where public and named
- official legal-framing records already in case study 01
- explicit local crosswalk back to decision and program nodes

After that, the next legal follow-on should be:

1. direct TRO / preliminary-injunction order capture for `Boyd`
2. only then `Grants Pass` and the broader pressure-test basket

That is enough to justify a later first-class legal lane without pretending the entire judicial model is done.

## First Import Scope

Do not import every bundle on day one.

Start with the San Rafael governance spine:

1. canonical seeds
2. election records
3. city campaign filings / IE
4. Form 460 schedules
5. Form 803
6. homelessness case study bundle
7. August 19 item `5.a` record splits

Import only these object classes from those bundles:

- canonical entities and officeholding
- meetings, agenda items, and decisions
- committees, filings, and disclosures
- money flows
- records
- `ValidationCheck`

Defer for phase two:

- campaign discovery bundle
- all media worked-example files
- permit basket
- procurement basket
- criminal sample basket
- broader legal/oversight bundle beyond the first named precedent set

## Main Risks

### Risk 1: Discovery/demo pollution

If discovery-stage bundles and worked-example files land in core import, the graph will overstate certainty and mix demo artifacts with durable civic objects.

Mitigation:

- projection layer excludes discovery-stage and worked-example artifacts from v1
- default v1 import to durable bundle objects only

### Risk 2: OCR actor pollution

Weak OCR-derived donor or vendor labels should not become durable `Actor` nodes in the first import.

Mitigation:

- keep row-level money flows
- defer weak OCR actor promotion unless a stronger canonical actor already exists
- allow unresolved labels to remain raw strings in the projection output instead of forced `Actor` nodes

### Risk 3: Duplicate semantics across bundles

The same actor or record can appear in several bundles.

Mitigation:

- manifest ordering
- `MERGE` by stable ID only
- no importer-side fuzzy resolution

### Risk 4: Legal / precedent layer still looks thinner than it really is

The legal work is now normalized, but still easy to miss because the first bundle is narrow and stays outside core graph-v1 import.

Mitigation:

- keep legal context visible in the page architecture
- keep `legal-precedent-01` visible as a real lane
- do not promise a top-level legal tab until the bundle is stronger than the current Boyd-only slice

### Risk 5: Overbuilding the importer

If the importer tries to solve extraction, validation, and identity resolution, it will become brittle.

Mitigation:

- importer only materializes projection output
- projection only normalizes bundle shape and scope
- extraction stays in extraction scripts
- identity resolution stays in the normalized layer and seed bundles

## Post-Review Position

After adversarial review, the recommended stance is:

- projection layer first
- narrow San Rafael governance spine for v1
- `ValidationCheck` in v1
- `Mention` and `Claim` out of core v1
- no top-level `Records` tab in v1
- no top-level `Legal & Precedent` tab until `legal-precedent-01` matures beyond the current Boyd-only slice

## Adversarial Review Questions

- Is the projection layer sufficient to keep bundle-local semantics out of `load_neo4j_v1.py`?
- Should weak OCR actor labels materialize as nodes, or stay attached to money-flow raw labels until stronger identity exists?
- Is `ValidationCheck` narrow enough to import now while `Mention` and `Claim` stay out of core v1?
- Is a top-level `Legal & Precedent` tab still premature while `legal-precedent-01` is only a Boyd-first slice with an unresolved TRO / injunction gap?
- Are permits and procurement better left for phase two until the San Rafael governance spine is proven?

## Recommended Next Commit

If this proposal survives review, the next implementation tranche should be:

- `registry/import-manifest.yaml`
- `scripts/build_graph_projection.py`
- `scripts/load_neo4j_v1.py`
- `scripts/graph_smoke_checks.py`
- one import of the San Rafael governance spine
- one query note showing 3 to 5 real graph traversals
- one follow-on normalized legal slice for `Boyd` only
