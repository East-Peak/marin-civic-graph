# Judicial Pressure-Test Basket Ingestion Checklist

Date drafted: April 10, 2026

This checklist turns the judicial / oversight pressure-test basket into an execution plan.

References:

- [Judicial And Oversight Extension](./judicial-and-oversight-extension.md)
- [Judicial Pressure-Test Basket Source Bundle](./judicial-pressure-test-basket-source-bundle.md)

## Goal

Produce the first multi-case legal and oversight bundle for Marin Civic Graph.

That means collecting enough material to pressure-test:

- `Case`
- `Proceeding`
- `ReliefRequest`
- `CaseParticipation`
- `Record` with `legal_record`
- `OversightReport`
- `Finding`
- `Recommendation`
- `AgencyResponse`
- the joins back into `Decision`, `Program`, `Institution`, and `Place`

## Basket

The first pass covers:

1. `Boyd v. City of San Rafael`
2. `City of Grants Pass v. Johnson`
3. `Coalition on Homelessness v. City and County of San Francisco`
4. one Marin Civil Grand Jury homelessness / oversight report

## Phase 0: Source Registration

### Must Register First

- [x] San Rafael `Boyd` dismissal release
- [x] San Rafael `Grants Pass` statement
- [x] San Rafael `Grants Pass` explainer
- [x] Supreme Court docket for `City of Grants Pass v. Johnson`
- [x] SF City Attorney `Grants Pass` amicus page
- [x] SF City Attorney Coalition appeal page
- [x] SF City Attorney Coalition vacatur page
- [x] SF City Attorney Coalition narrowed-scope page
- [x] SF City Attorney Coalition settlement page
- [x] Marin Civil Grand Jury reports index
- [x] Marin Civil Grand Jury prior-to-2018 report-name index
- [x] Marin Civil Grand Jury 2017-2018 homelessness report PDF

### Registry Metadata To Capture

- [x] source ID
- [x] source owner
- [x] source category
- [x] fetch strategy
- [x] expected objects
- [x] review risk
- [x] notes on 403 / browser-friendly fetch behavior where observed

## Phase 1: Raw Capture

### Boyd / San Rafael

- [x] capture the San Rafael `Boyd` dismissal release as raw HTML
- [x] identify whether the release links to or references the operative dismissal order
- [x] isolate the August 19 staff-report passages that summarize the case
- [x] tie those passages back to already captured item `5.a` records

### Grants Pass

- [x] capture the Supreme Court docket page as raw HTML
- [x] capture the linked opinion PDF or official opinion page
- [x] capture the SF City Attorney `Grants Pass` amicus page
- [x] capture the District of Oregon opinion and judgment
- [x] capture the official Ninth Circuit amended opinion
- [x] tie San Rafael's statement and explainer pages into the same legal thread

### Coalition On Homelessness

- [ ] capture the opening-brief explainer page
- [ ] capture the vacatur page
- [ ] capture the narrowed-scope page
- [ ] capture the settlement page
- [ ] download any linked PDF orders or briefs that are publicly attached

### Marin Civil Grand Jury

- [ ] capture the reports index page
- [ ] capture the prior-to-2018 report-name index page
- [ ] capture the 2017-2018 homelessness report PDF
- [ ] find and capture a formal response if discoverable from the public indexes

## Phase 2: Record Extraction

### Legal Records

- [x] create `Record` candidates for each captured page / PDF
- [x] classify them as:
  - complaint / petition / motion / order / opinion / settlement / official statement
- [x] extract dates, titles, and named parties
- [x] preserve links between public explainers and any attached orders or briefs

### Oversight Records

- [ ] create `Record` candidates for the report index and the report PDF
- [ ] extract report title, date, and issuing body
- [ ] identify discrete findings
- [ ] identify discrete recommendations
- [ ] identify response posture if any response record is found

## Phase 3: Case And Oversight Object Modeling

### Boyd

- [x] create `Case`
- [x] create initial `CaseParticipation` candidates
- [ ] create `Claim` candidates for the injunction / dismissal timeline
- [x] connect the case to the August 19 ordinance / resolution decisions
- [x] connect the case to the sanctioned camping program records

### Grants Pass

- [x] create `Case`
- [x] create `CaseParticipation` for city/amicus actors where explicit
- [x] create a `Record` for the opinion
- [x] create district / appellate / Supreme Court case-lineage objects
- [ ] create `Claim` candidates describing the local legal effect only where explicit in official records
- [x] connect San Rafael and SF response records back to the case

### Coalition On Homelessness

- [ ] create `Case`
- [ ] create `Proceeding` candidates for appeal / vacatur / settlement stages
- [ ] create `ReliefRequest` candidates for preliminary injunction and later narrowed relief
- [ ] create `Claim` candidates for surviving claims and narrowed scope
- [ ] keep ambiguous legal summaries in `Claim`, not canonical truth

### Marin Civil Grand Jury

- [ ] create `OversightReport`
- [ ] create `Finding` candidates
- [ ] create `Recommendation` candidates
- [ ] create `AgencyResponse` candidate if a formal response is found
- [ ] create `Decision` or `Program` links only where later implementation is explicit

## Phase 4: Join Back To The Civic Graph

### Required Links

- [ ] case -> institution
- [ ] case -> actor
- [ ] record -> case
- [ ] record -> proceeding
- [ ] relief request -> institution / decision / program
- [ ] legal record -> constrains decision / program / institution
- [ ] decision -> responds to case
- [ ] oversight report -> finding / recommendation
- [ ] agency response -> oversight report
- [ ] decision -> implements recommendation

### San Rafael Crosswalk

- [ ] connect `Boyd` to item `5.a`
- [ ] connect `Boyd` to Ordinance `2040`
- [ ] connect Resolution `15336` to the sanctioned camping program
- [ ] connect San Rafael legal explainer pages to those same decision/program nodes

## Phase 5: Minimum Deliverable

The first usable legal / oversight deliverable should be:

- [ ] one `Case` page-worth of data for `Boyd`
- [x] one `Case` page-worth of data for `Grants Pass`
- [ ] one `Case` page-worth of data for `Coalition on Homelessness`
- [ ] one `OversightReport` page-worth of data for the Marin Civil Grand Jury sample
- [x] one `Case` page-worth of data for `Boyd`
- [ ] one cross-case timeline showing how external legal constraints fed into local San Rafael action
- [ ] one clear example of a `Claim` that remains unpromoted because the public record is too ambiguous

## Blocking Questions

- [ ] can we find a clean public docket or order source for the operative `Boyd` injunction and dismissal order?
- [x] should the Supreme Court opinion PDF for `Grants Pass` be its own `source_id` or just a docket-discovered artifact?
- [ ] how much of `Coalition on Homelessness` can be modeled from official city-attorney pages before deeper docket work is necessary?
- [ ] where are Marin agency responses to the homelessness-related grand-jury report surfaced publicly?
- [ ] do we need a dedicated `oversight_record` subclass later, or is `legal_record` / `program_record` enough for v1?

## Practical Order Of Operations

If doing this manually first, the order should be:

1. capture `Grants Pass` docket and opinion
2. capture SF City Attorney Coalition pages
3. promote already-held San Rafael `Boyd` / `Grants Pass` records into legal objects
4. capture one Marin Civil Grand Jury report and index pages
5. build case / report objects
6. connect them back to San Rafael decisions and programs

## Status As Of April 10, 2026

- the source basket and registry seeds now exist
- the San Rafael side of the legal context is already partially captured through case study 01
- the repo now has two real normalized legal bundles:
  - `legal-precedent-01` for `Boyd v. City of San Rafael`
  - `legal-precedent-02` for `City of Grants Pass v. Johnson`
- the remaining work is deeper legal comparison beyond the first Grants Pass lower-court chain, stronger supporting provenance, and the eventual join back into the civic graph

This checklist should be the first legal / oversight implementation slice after the current San Rafael official bundle.
