# Case Study 01 Ingestion Checklist

Date drafted: April 10, 2026

This checklist turns Case Study 01 into an execution plan.

Reference:

- [Case Study 01](./01-san-rafael-homelessness.md)

## Goal

Produce the first end-to-end evidence chain for the San Rafael homelessness / encampments thread.

That means collecting enough material to instantiate:

- institutions
- actors
- meetings
- agenda items
- decisions
- documents
- money flows
- article mentions
- places

## Phase 0: Source Registration

### Must Register First

- [ ] San Rafael City Council meetings page
- [ ] August 19, 2024 council meeting page
- [ ] August 19, 2024 staff report landing page
- [ ] San Rafael `Grants Pass` statement page
- [ ] San Rafael `Grants Pass` explainer / FAQ page
- [ ] San Rafael camping implementation page
- [ ] San Rafael sanctioned camping area page
- [ ] San Rafael homelessness update pages for June 2024, November 2024, January 2025
- [ ] San Rafael disclosures page
- [ ] Marin County campaign finance portal
- [ ] relevant Marin IJ entry points for this issue

### Registry Metadata To Capture

- [ ] source ID
- [ ] source owner
- [ ] source category
- [ ] fetch strategy
- [ ] expected objects
- [ ] review risk
- [ ] paywall status

## Phase 1: Official Document Collection

### Priority 1 Documents

- [ ] July 2023 camping ordinance materials
- [ ] May 6, 2024 ordinance amendment materials
- [ ] August 19, 2024 staff report PDF
- [ ] August 19, 2024 agenda and packet attachments
- [ ] August 19, 2024 meeting video
- [ ] August 19, 2024 minutes once located
- [ ] `Grants Pass` city statement
- [ ] `Grants Pass` city explainer / FAQ
- [ ] news release on `Boyd` dismissal
- [ ] camping implementation approach page and linked administrative orders
- [ ] sanctioned camping area operating pages and updates

### Output Required

- [ ] each document stored as raw artifact
- [ ] each document classified by type
- [ ] extracted text available
- [ ] canonical document metadata assigned

## Phase 2: Meeting and Decision Extraction

### August 19, 2024 Meeting

- [ ] create `Meeting`
- [ ] enumerate relevant `AgendaItem` objects
- [ ] identify all formal `Decision` candidates
- [ ] extract any vote tables or motions
- [ ] extract linked contracts, appropriations, and grant references

### Earlier Ordinance Steps

- [ ] identify July 2023 decision object
- [ ] identify May 6, 2024 decision object
- [ ] connect each to ordinance documents and related places

## Phase 3: Place Layer

### Must Normalize

- [ ] Mahon Creek Path
- [ ] Lindaro Street
- [ ] Andersen Drive
- [ ] Francisco Blvd W
- [ ] Albert Park
- [ ] Menzies parking lot
- [ ] 350 Merrydale Road

### Output Required

- [ ] canonical place IDs
- [ ] normalized aliases
- [ ] lat / lon where safe
- [ ] linked decisions and documents

## Phase 4: Actor Seed Build

### Public Officials / Staff

- [ ] current council actors referenced in the thread
- [ ] city manager actor
- [ ] city attorney / outside counsel actors where named

### Operators / Nonprofits / Contractors

- [ ] Downtown Streets Team
- [ ] Ritter Center
- [ ] Homeward Bound
- [ ] St. Vincent de Paul
- [ ] FS Global
- [ ] Defense Block Security

### Litigation Actors

- [ ] named plaintiffs in `Boyd`
- [ ] plaintiff counsel
- [ ] city counsel

### Output Required

- [ ] actor records
- [ ] initial aliases
- [ ] institution links
- [ ] membership candidates where supported

## Phase 5: Money and Contract Extraction

### Priority Targets

- [ ] Encampment Resolution Fund grant
- [ ] August 19, 2024 appropriations
- [ ] August 19, 2024 contracts
- [ ] contractor names, amounts, and durations
- [ ] nonprofit program roles where funding is explicit

### Output Required

- [ ] `MoneyFlow` candidates
- [ ] linked `Decision` objects
- [ ] recipient and payer actors
- [ ] evidence documents

## Phase 6: Media Layer

### Article Collection

- [ ] collect core Marin IJ pieces on this thread
- [ ] collect other relevant local coverage
- [ ] capture citation metadata even when full text is unavailable

### ArticleMention Extraction

- [ ] isolate quoted people
- [ ] preserve role label as printed
- [ ] preserve affiliation label as printed
- [ ] mark unresolved names for review

### Attribution Review

- [ ] check whether quoted people recur in meeting comments
- [ ] check whether quoted people appear in org rosters
- [ ] check whether quoted people appear in campaign or disclosure records
- [ ] separate article framing from corroborated affiliation

## Phase 7: Minimum Deliverable

The first usable deliverable for this case study should be:

- [ ] one timeline from July 2023 to January 2025
- [ ] one actor table
- [ ] one place table
- [ ] one decision chain centered on August 19, 2024
- [ ] one media-attribution sample showing at least one recurring quoted actor pattern if present

## Blocking Questions

- [ ] where exactly do the August 19, 2024 attachments live, and do they expose contract detail cleanly?
- [ ] are the meeting minutes sufficiently detailed to extract vote records directly?
- [ ] which local-media pieces require subscription access versus open citation capture?
- [ ] what is the cleanest official source for the ERF grant amount and program obligations?

## Practical Order Of Operations

If doing this manually first, the order should be:

1. register sources
2. collect official pages and PDFs
3. build the August 19, 2024 meeting package
4. normalize places
5. normalize actors
6. extract money flows
7. layer in media

That will create the first trustworthy version of the case without over-relying on media before the official spine exists.
