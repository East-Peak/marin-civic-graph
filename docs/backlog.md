# Backlog

This file is the working backlog and wish list for Marin Civic Graph.

It is intentionally mixed:

- near-term planning tasks
- medium-term product tasks
- longer-term wishlist ideas

The goal is to keep good ideas from disappearing into chat history.

Note:

- unresolved source ambiguities and modeling questions now live in [open-questions.md](./open-questions.md)
- this file stays focused on backlog and wishlist work, not active join ambiguity

## Near-Term

### Case Study 01

Build the first real case study around one Marin thread.

Candidates:

- San Rafael homelessness / encampments
- San Rafael parking / street design
- one Marin County Board of Supervisors item with documents, speakers, vote, and implementation trail

### Source Registry Format

Define the source-manifest shape that ingestion agents will use.

Should include:

- source ID
- jurisdiction / institution owner
- source type
- fetch strategy
- expected objects
- cadence
- review risk

### Municipality Source Profiles

Build jurisdiction-by-jurisdiction source profiles that document where each record family actually lives.

Should cover:

- meetings
- campaign filings
- disclosure filings
- public-records portals
- permit systems
- contracts / procurement
- court / oversight surfaces where relevant

Why this matters:

- the project is not integrating one platform
- each municipality and county surface has different quirks, indexing rules, and fetch constraints
- these profiles should become the operational map for adapters, backfill, and cron

### Media Attribution Rules

Write a review rubric for quoted people in local media.

Should distinguish:

- article framing
- explicit article affiliation
- corroborated external affiliation
- unresolved ambiguity

## Medium-Term

### Record Node Taxonomy

Formalize `Record` as a first-class graph node family.

Should cover:

- meeting records
- legislative records
- media records
- financial records
- contract records
- legal records
- program records

Immediate implication:

- Marin IJ article, ordinance, resolution, minutes, packet, and contract should all exist as typed record nodes

### Permit Thread Pressure Test

Pressure-test the permits / applications / determinations layer on one real project thread.

Should include:

- project
- application
- hearing notice
- staff report
- determination
- permit or denial
- appeal if present

Why this matters:

- many consequential local decisions happen before they ever reach a city council or board spotlight

### Marin Monitor Civic / Governance Feed

Create a governance-oriented feed or section inside Marin Monitor that automatically ingests civic-process signals into a dedicated panel or wire.

Possible scope:

- city council agendas
- county board agendas
- meeting minutes
- planning commission items
- disclosures
- campaign finance updates

Possible phases:

1. RSS-first civic wire using existing Marin Monitor feed patterns
2. supplement with document-derived meeting items from Marin Civic Graph
3. eventually expose richer actor / decision context from the graph back into Marin Monitor

Why this matters:

- Marin Monitor already has audience, runtime, and ingestion patterns
- a lightweight civic/governance section is the fastest way to make this project visible before the full graph product exists

### Article Framing Gap View

Build a view showing when a person quoted in local media recurs elsewhere as:

- public commenter
- activist
- nonprofit affiliate
- board member
- donor

Without overstating the claim.

### Actor Pages

Stand up first-class actor pages that unify:

- affiliations
- comments
- money
- meetings
- mentions
- related issues

### Ordinance / Resolution Ingestion

Promote ordinances and resolutions from attachment text into first-class record and decision objects.

Should include:

- ordinance record nodes
- resolution record nodes
- adoption / introduction status
- links back to meeting, agenda item, and vote
- links forward to contracts, appropriations, and implementation pages

Why this matters:

- many of the most important local actions are formalized in ordinance and resolution text, not just staff reports or minutes

### Campaign Finance / Disclosure Pressure Test

Pressure-test the campaign-finance and disclosure layer on one real local basket.

Should include:

- one candidate-controlled committee
- one outside-money or late-contribution thread
- one Form 700 or Form 803 disclosure thread
- joins back to seat, officeholder, and at least one other civic domain

Why this matters:

- this is one of the strongest recurring-actor surfaces in the project
- it is where donor, committee, officeholder, and disclosure data stop being abstract and start joining back into permits, contracts, meetings, and appointments

### Historical Backfill Plan

Formalize the first large backfill window and source ordering.

Suggested baseline:

- sweep recurring high-value sources back to at least `2019-01-01`

Should include:

- source families
- earliest target date by family
- archive-walk strategy
- stop conditions and known exceptions

Why this matters:

- the project will eventually need multi-year context, not just forward collection
- backfill should be deliberate and repeatable instead of ad hoc

### Cron Rollout Plan

Formalize recurring sync after initial backfill.

Should include:

- weekly default cadence for stable sources
- daily cadence for faster-changing sources
- manual exceptions
- expected manifest/diff outputs per run

Why this matters:

- the graph needs an ongoing operating model, not just one-time data grabs

### Exhibit And Attachment Splitting

Split dense packet items into child records rather than leaving everything buried inside one PDF.

Examples:

- contract exhibit
- code of conduct
- site plan
- public correspondence packet

Why this matters:

- the graph should ingest records as records, not just preserve them as page ranges inside a giant packet

### Procurement / Grant Pressure Test

Pressure-test the procurement, grant, contract, and performance layer on one county thread and one city thread.

Should include:

- solicitation
- approval decision
- operative agreement
- amendment or renewal
- program or project linkage
- audit or performance surface if public

Why this matters:

- this is one of the strongest accountability surfaces for NGOs, vendors, consultants, and public spending

## Longer-Term

### NGO Influence Map

Show nonprofit, contractor, grant, and coalition networks around a policy issue.

### County / City Contract Layer

Track:

- contracts
- renewals
- amendments
- vendor and grantee recurrence

### Appointment and Vacancy Tracker

Track:

- seats
- appointers
- current occupants
- term expiration
- vacancy status

### Judicial / Court Extension

Possible later-phase work only for civil and public-law expansion.

Would need:

- case tracking
- judge pages
- prosecutor / public defender / city attorney links
- careful methodology for any downstream outcome claims

### Criminal Justice / Judge Accountability Layer

Track public criminal-case surfaces in a way that is evidence-first and methodologically defensible.

Should cover:

- booking and custody events
- warrant surfaces
- criminal case metadata
- hearings and proceedings
- attorney roles
- dispositions and sentences where publicly available
- judge assignments and recurrence

Why this matters:

- lower-level judges exercise real power with weak public scrutiny
- this creates a public-safety and accountability layer that is adjacent to, but distinct from, civil litigation
- the graph should make it easier to see recurring patterns without turning anecdote into a scorecard

Important constraint:

- start with public case index and hearing data, not a broad criminal-docket mirror
- keep any judge-evaluation view downstream and derived from explicit event-level records

### Commercial People-Search Evaluation

Revisit later whether a commercial people-search or background-check service is useful as an optional operator-assisted research aid.

Examples to revisit:

- `publicdatacheck.com`
- other services with APIs, bulk export, or better matching controls

Possible uses:

- operator-side identity disambiguation for already-public named cases
- cross-checking whether two public records likely refer to the same adult person
- backfilling non-core metadata where official records are too thin

Important constraint:

- do not make a commercial people-search vendor a core dependency of the graph
- do not treat third-party people-search output as primary evidence
- if revisited, evaluate API access, terms of use, legal risk, matching quality, and how any output would be kept outside the core official-record truth layer

### State / Federal / Quasi-Governmental Governance Layer

Track outside institutions that materially constrain Marin outcomes even when they are not ordinary municipal bodies.

Should cover:

- Coastal Commission
- Caltrans
- state parks
- federal land managers
- special districts
- land trusts and conservancies when they hold operational leverage, contracts, easements, or advisory influence

Why this matters:

- a large share of Marin land and development friction sits outside normal city-council process
- this creates an “external veto point” layer that the graph should make legible

### Permits / Applications / Denials Layer

Track the administrative process around things that never become a big council item but still matter.

Should cover:

- permit applications
- discretionary applications
- denials
- conditions of approval
- appeals
- staff determinations
- hearing notices

Why this matters:

- many real local power fights happen in administrative review, not just headline council votes
- this creates a second major constraint surface alongside courts and oversight
- it connects well to land use, homelessness facilities, shelter approvals, street changes, and public-space regulation

## Parking Lot

Ideas worth keeping but not prioritizing yet:

- issue-specific email digests
- alerts when recurring actors appear on an issue again
- map overlays for projects, hearings, and place-based disputes
- public-comment archive with speaker recurrence
- local power map / org-chart view
- optional operator-side commercial lookup tooling for identity disambiguation, including `publicdatacheck.com`
