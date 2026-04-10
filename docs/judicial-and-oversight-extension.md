# Judicial And Oversight Extension

Date drafted: April 10, 2026

This document extends the graph model for litigation, injunctions, grand jury reports, and other formal oversight surfaces.

The goal is to capture the legal and oversight layers that often constrain local government action without overreaching into inaccessible or low-value court material.

## Scope

The first target is not "all court records."

The first target is public-law and government-accountability material that directly affects municipal and county behavior.

Priority categories:

- homelessness / encampments / sheltering litigation
- land use / CEQA and permitting disputes
- Brown Act / public records litigation
- policing / jail / civil-rights actions
- public contract disputes involving government money
- civil grand jury reports
- audit reports and formal agency responses

Low-priority later material:

- depositions
- discovery fights
- routine criminal-case ingestion outside the public-accountability basket documented elsewhere
- routine private civil litigation with little civic relevance

## Why This Matters

Many local decisions are not constrained mainly by elections or public meetings.

They are constrained by:

- lawsuits
- injunctions
- legal settlements
- grand jury findings
- audit findings
- counsel interpretations

The graph needs to answer questions like:

- which case blocked or forced this city action?
- which injunction narrowed the city's options?
- which judge signed the order?
- which recommendation did the agency accept or reject?
- what program or ordinance changed afterward?

## First-Pass Node Types

### Case

Use for the durable dispute object.

Examples:

- `Boyd v. City of San Rafael`
- `City of Grants Pass v. Johnson`

Key fields:

- `id`
- `name`
- `case_type`
- `court_name?`
- `docket_number?`
- `status`
- `filed_at?`
- `closed_at?`

### Court

Treat this as an `Institution` subtype in the main model, but it is worth calling out explicitly here.

Examples:

- U.S. District Court, Northern District of California
- Ninth Circuit
- Marin County Superior Court

### Judge

Treat judges as `Actor` nodes with a `judge` role.

Useful fields:

- `id`
- `canonical_name`
- `court_ids[]`
- `status?`

### Proceeding

Use for a bounded hearing, calendar event, or filing-stage event inside a case.

Examples:

- TRO hearing
- preliminary injunction hearing
- motion to dismiss hearing
- settlement conference

Key fields:

- `id`
- `case_id`
- `proceeding_type`
- `scheduled_at?`
- `occurred_at?`
- `status`

### ReliefRequest

Use for the discrete legal relief being sought.

Examples:

- TRO
- preliminary injunction
- permanent injunction
- writ
- dismissal
- sanctions

Key fields:

- `id`
- `case_id`
- `relief_type`
- `status`
- `requested_at?`
- `decided_at?`

### CaseParticipation

Use for party, counsel, and amicus roles.

Examples:

- plaintiff
- defendant
- petitioner
- respondent
- counsel
- amicus

Key fields:

- `id`
- `case_id`
- `actor_id?`
- `institution_id?`
- `role`
- `started_at?`
- `ended_at?`

### Legal Record

Use the existing `Record` node with `record_class = legal_record`.

Priority `record_type` values:

- complaint
- petition
- answer
- motion
- opposition
- reply
- declaration
- exhibit
- minute_order
- injunction_order
- dismissal_order
- judgment
- settlement_agreement
- consent_decree
- opinion
- amicus_brief

### OversightReport

Use for formal non-judicial oversight artifacts.

Examples:

- civil grand jury report
- audit report
- inspector review
- monitor report

Key fields:

- `id`
- `report_type`
- `title`
- `issued_at`
- `issuing_institution_id?`
- `status`

### Finding

Use for one discrete claim or criticism made by an oversight report.

Key fields:

- `id`
- `report_id`
- `finding_type`
- `summary`
- `severity?`

### Recommendation

Use for one recommended corrective action.

Key fields:

- `id`
- `report_id`
- `recommendation_type`
- `summary`

### AgencyResponse

Use for the formal response by a city, county, department, or office.

Key fields:

- `id`
- `report_id`
- `institution_id`
- `response_status`
- `responded_at`
- `response_record_id?`

Suggested `response_status` values:

- agree
- partially_agree
- disagree
- unclear

## Core Relationships

### Case Layer

- `Case` `INVOLVES` `Actor`
- `Case` `INVOLVES` `Institution`
- `Proceeding` `PART_OF` `Case`
- `ReliefRequest` `PART_OF` `Case`
- `Judge` `PRESIDED_OVER` `Proceeding`
- `Record` `FILED_IN` `Case`
- `Record` `FOR_PROCEEDING` `Proceeding`
- `Record` `SEEKS_RELIEF` `ReliefRequest`
- `Record` `DECIDES_RELIEF` `ReliefRequest`
- `Record` `REPORTS_ON_CASE` `Case`

### Constraint / Impact Layer

- `ReliefRequest` `TARGETS` `Decision`
- `ReliefRequest` `TARGETS` `Program`
- `ReliefRequest` `TARGETS` `Institution`
- `Record` `CONSTRAINS` `Decision`
- `Record` `CONSTRAINS` `Program`
- `Record` `CONSTRAINS` `Institution`
- `Decision` `RESPONDS_TO` `Case`
- `Decision` `RESPONDS_TO` `OversightReport`

### Oversight Layer

- `OversightReport` `HAS_FINDING` `Finding`
- `OversightReport` `HAS_RECOMMENDATION` `Recommendation`
- `AgencyResponse` `RESPONDS_TO` `OversightReport`
- `Institution` `RECEIVED_RECOMMENDATION` `Recommendation`
- `Decision` `IMPLEMENTS` `Recommendation`
- `Record` `MEMORIALIZES_RESPONSE` `AgencyResponse`

## What To Ingest First

### High-Value Judicial Records

Start with:

- complaints and petitions
- motions for TRO / preliminary injunction
- injunction orders
- minute orders
- dismissal orders
- judgments
- settlement agreements and consent decrees
- appellate opinions
- amicus briefs when they shape the public-law context
- filed declarations and exhibits when public and material

Do not start with:

- deposition transcripts
- discovery correspondence
- routine scheduling noise
- broad criminal court ingestion

### High-Value Oversight Records

Start with:

- Marin civil grand jury reports
- county and city responses
- state audit reports
- formal corrective-action plans
- public monitor or compliance reports where they exist

## Promotion Rules

Safe to promote directly:

- case caption from an official docket or filed order
- named judge from the signed order
- granted or denied relief from the operative order
- filing date from the docket or filed document
- agency agreement / disagreement from the formal response text

Usually keep as a `Claim` first:

- informal descriptions of what an order "really means"
- inferred downstream operational effects unless tied to a later decision or program record
- secondhand media characterizations of legal posture
- identity resolution for common-name litigants or attorneys

## Worked Example: Boyd -> Injunction -> Ordinance -> Program

This is the first real judicial chain the project should support.

### Canonical Nodes

- `case-boyd-v-city-of-san-rafael`
- `inst-city-of-san-rafael`
- `inst-us-district-court-ndca`
- `actor-judge-edward-chen`
- `program-sanctioned-camping-area`
- `decision-2024-08-19-ordinance-2040-introduction`
- `decision-2024-08-19-resolution-15336`

### Legal Records

- complaint or petition record if public
- preliminary injunction order record
- dismissal order record
- city news release summarizing dismissal
- later staff report record describing the legal posture

### Example Relationship Chain

- `case-boyd-v-city-of-san-rafael` `INVOLVES` `inst-city-of-san-rafael`
- injunction order `FILED_IN` `case-boyd-v-city-of-san-rafael`
- injunction order `CONSTRAINS` `inst-city-of-san-rafael`
- injunction order `CONSTRAINS` `decision-2024-08-19-ordinance-2040-introduction`
- dismissal order `DECIDES_RELIEF` preliminary injunction request
- August 19 staff report `REPORTS_ON_CASE` `case-boyd-v-city-of-san-rafael`
- August 19 staff report `record_introduces_decision` `decision-2024-08-19-ordinance-2040-introduction`
- resolution `15336` `IMPLEMENTS` `program-sanctioned-camping-area`
- the city's sanctioned camping pages `record_implements_decision` `decision-2024-08-19-resolution-15336`

### Query This Should Enable

- "Show every record that constrained San Rafael's camping enforcement before August 19, 2024."
- "Show the legal sequence from Boyd through dismissal to the sanctioned camping rollout."
- "Show which official city decisions and program pages explicitly responded to the litigation."

## Immediate Design Implications

Three concrete implications follow:

1. Judicial and oversight material fits inside the existing layered graph model; it does not require a separate architecture.
2. The first public-law legal wedge should be injunction-driven municipal cases, not broad court scraping.
3. After this layer, the next administrative expansion should probably be permits, applications, denials, and appeals because they form a parallel non-judicial constraint surface.

## Recommended Next Step

Use the San Rafael homelessness case study as the first pressure test:

1. add a `Case` node for `Boyd v. City of San Rafael`
2. register the key legal and city-summary records
3. model the injunction / dismissal chain
4. connect it to Ordinance `2040`, Resolution `15336`, and the sanctioned camping program

## Recommended Pressure-Test Basket

Do not rely on only one case.

Use a small basket that produces different legal and oversight shapes.

### 1. Boyd v. City of San Rafael

Why it matters:

- directly tied to case study 01
- gives the local district-court / injunction / dismissal pattern
- connects cleanly to official city records, ordinances, resolutions, and program rollout

What to ingest:

- case node
- injunction-related records that are public
- dismissal order or official summary record
- city news release
- staff reports and implementation records that reference the case

### 2. City of Grants Pass v. Johnson

Why it matters:

- gives the Supreme Court precedent layer
- provides docket, amicus, argument, and opinion patterns
- explains why many local governments changed their enforcement posture in 2024

What to ingest:

- case node
- Supreme Court docket record
- slip opinion record
- key amicus records where relevant
- local government response records that cite the decision

### 3. Coalition on Homelessness v. City and County of San Francisco

Why it matters:

- gives the large-city injunction / modification / appeal / settlement pattern
- includes district-court orders, Ninth Circuit activity, city attorney responses, and later settlement
- helps model partial vacatur, surviving claims, and policy constraints that evolve over time

What to ingest:

- case node
- preliminary injunction record
- motion-to-modify record
- Ninth Circuit memorandum / order record
- city attorney statements and settlement records

### 4. Marin Civil Grand Jury Homelessness Reports

Why it matters:

- this is not litigation, which is exactly why it belongs in the basket
- it pressure-tests the oversight side: report -> finding -> recommendation -> agency response
- it is Marin-specific and often easier to obtain cleanly than court dockets

What to ingest:

- oversight report node
- report record
- finding and recommendation nodes
- county or city response records
- later decisions or program changes that appear to implement recommendations

### Optional 5th Pressure Test: Funding / Grants Litigation

If a fifth item is needed, choose a public-law grants case involving homelessness funding conditions rather than a private dispute.

Why:

- it adds the "grant conditions / injunction / program funding" pattern
- it broadens the model beyond camping enforcement while staying in the homelessness/governance lane

## Why This Basket Is Better Than One Case

Together these samples cover:

- local injunction and dismissal
- Supreme Court precedent
- appellate modification of an injunction
- settlement and surviving claims
- non-judicial oversight reports and formal responses

That is enough variety to tell us:

- which legal record types are worth scraping first
- which relationships need to exist in the graph
- where `Claim` and `Mention` are actually necessary
- how court and oversight material connects back to meetings, programs, and decisions
