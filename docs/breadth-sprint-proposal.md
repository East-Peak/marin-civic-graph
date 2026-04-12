# Controlled Breadth Sprint Proposal

Verified: April 12, 2026

This proposal defines the next project phase after adversarial review.

The goal is no longer "widen all proven source families at once." The goal is to improve graph density on one strong local loop before opening broader county lanes.

## Why This Phase Still Matters

The project is not blocked on ontology.

It already has:

- stable IDs and explicit join rules
- a working projection layer and live Neo4j load
- durable normalized bundles across meetings, campaign finance, disclosures, legal, permits, procurement, and media
- a repo-local and workspace-level decision trail

The new bottleneck is join density, not raw material.

Current graph-v1 already contains:

- `338` `Record` nodes
- `233` `Filing` nodes
- `145` `MoneyFlow` nodes

But it only contains:

- `19` `Actor` nodes
- `26` `Meeting` nodes
- `23` `Decision` nodes
- `5` `SeatService` nodes

And it is still skipping `147` edges because the actor side is too thin.

That means the wrong next move is a broad five-track backfill that mostly creates more filings and records without materially strengthening the graph questions we care about.

## Phase Rule

During this sprint:

- freeze schema by default
- avoid new domain tranches
- prefer join density over document volume
- treat county-wide expansion as conditional, not automatic

A new node type is only justified if:

1. a real source cannot be represented cleanly without it
2. a real query cannot be answered without it
3. the same object boundary appears in multiple source families

## Objective

Build a denser San Rafael civic spine so graph-v1 can answer recurring officeholder, decision, disclosure, campaign, and validation questions across multiple years without leaning on one-off examples.

## In Scope

### Track A: San Rafael City Council `2019+`

Goal:

- build the durable meeting / agenda / decision / vote backbone from `2019-01-01` forward
- keep agenda, packet, minutes, and video availability explicit

Expected yield:

- `Meeting`
- `AgendaItem`
- `Decision`
- `VoteCast`
- `Record`

Why:

- this is the cleanest path to more `Meeting`, `Decision`, and evidence density
- it directly addresses the current graph imbalance
- it is the strongest local decision spine for later joins into money, media, procurement, and legal constraints

### Track B: San Rafael Elected Disclosure Continuity

Goal:

- keep local Form `803` current
- backfill only the Form `700` slice that resolves cleanly to existing canonical officeholders and `SeatService` objects

Expected yield:

- `EconomicInterestDisclosure`
- `Filing`
- `MoneyFlow: behested_payment`
- `Actor`
- `Seat`
- `SeatService`
- `Record`

Boundary:

- do not import the full visible Form `700` archive across all `261` filers
- do not promote broad staff / commission disclosure volume until the elected-officeholder layer is denser

Why:

- this is the cleanest disclosure continuity path
- it improves officeholder dossier queries without creating a large unresolved actor-resolution burden
- Form `803` stays in scope because it is high-signal, but it is a maintenance lane, not an equal-volume backfill lane

### Track C: San Rafael City-Office Campaign Filing Backbone

Goal:

- deepen the city mayor / council filing spine for `2020`, `2022`, and `2024`
- broaden `Record`, `Filing`, `Committee`, and `Candidacy` coverage for city-office races
- keep broad row-level campaign money normalized-only unless it is already QA-backed

Expected yield:

- `Record`
- `Filing`
- `Committee`
- `Candidacy`
- `Election`
- `ValidationCheck`

Boundary:

- broader schedule-level `MoneyFlow` extraction stays normalized-only for now
- the current QA-backed `Form 460` sample remains usable in graph-v1
- non-city-office rows stay out

Why:

- this is the strongest path to actual local decision-to-finance overlap
- it improves committee / filing recurrence without forcing low-quality OCR actors into the core graph
- it gives the product a real city-election spine before county-wide expansion

## Conditional Later-Phase Candidate

Only after the fixed query pack improves materially:

- one normalized-only Marin County campaign-finance pilot

This is a checkpoint candidate, not part of the core sprint.

## Out Of Scope

Do not widen into these during this sprint:

- Marin County BOS `2019+` as a core sprint track
- Marin County campaign finance broad import
- full Form `700` archive import across all filers
- broad row-level city-side or county-side campaign `MoneyFlow` import beyond the current QA-backed sample
- non-city-office San Rafael campaign rows
- new legal case families beyond the current `Boyd` + `Grants Pass` pair
- broader permit backfill
- broader procurement backfill
- criminal expansion
- new media methodology
- new jurisdictions
- new major node families

These are valid later targets. They are not the current bottleneck.

## Execution Order

1. San Rafael City Council `2019+`
2. San Rafael Form `803` plus elected-officeholder Form `700`
3. San Rafael city-office campaign filing backbone
4. Stop and rerun the fixed query pack
5. Only if the graph improves materially, consider one normalized-only Marin County campaign-finance pilot

Marin County BOS moves to the next phase unless the city-side checkpoint proves the current graph still needs more meeting density before more finance density.

## Fixed Query Pack

Use the same query pack after each major checkpoint. Do not change the queries mid-sprint just to make the results look better.

### Q1: `actor-kate-colin` Dossier

Return:

- actor
- seat service
- council records
- city-side committees / filings
- local Form `803`
- imported Form `700` filings

Pass condition:

- spans multiple filing families and more than one year

### Q2: Current Elected Disclosure Coverage

Start from all current San Rafael `SeatService` nodes and return every imported Form `700` / `803` filing since `2019`.

Pass condition:

- every imported disclosure resolves to an existing canonical actor and `SeatService`

### Q3: San Rafael Council Decision Timeline

Return all San Rafael City Council `Decision` nodes since `2019` with meeting date, vote links, and evidence records.

Pass condition:

- the result is a real timeline, not just the August 19, 2024 worked example

### Q4: San Rafael Election Money Spine

For San Rafael mayor / council elections in `2020`, `2022`, and `2024`, return:

- committees
- filings
- IE filings
- only QA-backed money flows

Pass condition:

- recurrence appears across more than one cycle without importing noisy OCR actors as durable canonical people or orgs

### Q5: Validation Queue

Return every `ValidationCheck` and its subject filing, especially `filing-san-rafael-campaign-entry-37677`.

Pass condition:

- the queue stays bounded and legible instead of exploding with low-quality imports

## Deliverables

Minimum sprint deliverables:

- materially deepen the San Rafael council timeline from `2019-01-01`
- materially improve current elected disclosure continuity
- materially improve the San Rafael city-office campaign filing backbone
- rerun the fixed query pack and record before/after results
- keep graph-v1 projection, smoke checks, and live Neo4j load healthy

## Success Criteria

This sprint is successful if:

- the fixed query pack gets denser and more legible
- more imported filings and records resolve cleanly to existing actors, seats, and seat services
- the council decision timeline becomes a real multi-year spine
- the validation queue remains small enough to inspect directly
- graph-v1 improves by query usefulness, not just by node count

## Failure Modes To Watch

- treating all source families as equal-volume sprint lanes
- mistaking more filings for better joins
- full Form `700` import before the officeholder identity layer is ready
- broad campaign `MoneyFlow` import before OCR actor pollution is under control
- spending the sprint on county surfaces before the city loop is dense enough to judge product value
- widening import scope before the fixed query pack actually improves

## Recommended Next Slice

Start with San Rafael City Council `2019+`.

Reason:

- it is the strongest direct fix for the current graph imbalance
- it densifies `Meeting`, `Decision`, and evidence objects first
- it creates the best base for the later disclosure and campaign layers to land on

Do not open county-wide breadth again until that checkpoint proves we are getting graph value rather than just more artifacts.

## Decision Gate After Sprint

After the sprint checkpoint, decide one of:

- keep widening the San Rafael civic spine
- add one normalized-only Marin County campaign-finance pilot
- move BOS into the next phase

That decision should follow the fixed query pack results, not instinct.
