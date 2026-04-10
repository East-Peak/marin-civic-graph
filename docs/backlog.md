# Backlog

This file is the working backlog and wish list for Marin Civic Graph.

It is intentionally mixed:

- near-term planning tasks
- medium-term product tasks
- longer-term wishlist ideas

The goal is to keep good ideas from disappearing into chat history.

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

### Exhibit And Attachment Splitting

Split dense packet items into child records rather than leaving everything buried inside one PDF.

Examples:

- contract exhibit
- code of conduct
- site plan
- public correspondence packet

Why this matters:

- the graph should ingest records as records, not just preserve them as page ranges inside a giant packet

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

Possible later-phase work only.

Would need:

- case tracking
- judge pages
- prosecutor / public defender / city attorney links
- careful methodology for any downstream outcome claims

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
