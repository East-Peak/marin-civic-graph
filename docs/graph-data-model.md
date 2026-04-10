# Graph Data Model

Date drafted: April 10, 2026

This document defines what should live in the graph database.

The goal is to separate:

- canonical civic objects
- process and decision objects
- evidence-bearing records
- extracted-but-not-yet-promoted assertions

That lets the project answer civic questions without pretending every parser output is already graph truth.

## Design Goals

- keep the graph evidence-first
- preserve ambiguity when the source is ambiguous
- make records first-class
- avoid flattening everything into meetings or articles
- keep raw files and full text outside the graph

## What Lives In The Graph

The graph should store:

- canonical entities like actors, institutions, places, issues, programs, and cases
- process entities like meetings, agenda items, decisions, votes, comments, appointments, memberships, and money flows
- record nodes for ordinances, minutes, articles, contracts, packets, and filings
- extracted mentions and candidate claims when they are worth reviewing or linking
- references back to raw and extracted artifacts on disk

The graph should not store:

- full PDF or HTML blobs
- parser logs
- OCR intermediates
- every unreviewed token match

Those stay in `data/raw/` and `data/extracted/`.

## Layer 1: Canonical Context Nodes

These are the durable objects that users browse repeatedly.

### Actor

Use for people and outside organizations.

Subtypes:

- person
- nonprofit
- business
- PAC
- law firm
- union
- media outlet

Key fields:

- `id`
- `actor_type`
- `canonical_name`
- `aliases[]`
- `website?`
- `home_place_id?`
- `status?`

### Institution

Use for formal public bodies and organizational units.

Subtypes:

- city council
- county board
- department
- commission
- advisory body
- court

Key fields:

- `id`
- `institution_type`
- `name`
- `jurisdiction_place_id`
- `parent_institution_id?`
- `official_url?`
- `legal_basis_record_id?`

### Seat

Use for elected and appointed slots within institutions.

Key fields:

- `id`
- `institution_id`
- `name`
- `seat_type`
- `district?`
- `appointing_institution_id?`

### Place

Use for jurisdictions and specific locations.

Subtypes:

- county
- city
- district
- facility
- park
- street
- corridor
- parking_lot
- address

### Issue

Use for recurring policy areas.

Examples:

- homelessness
- encampments
- parking
- housing
- public safety

### Program

Use for ongoing operational efforts that are not just one decision or one place.

Examples:

- sanctioned camping program
- SAFE Team
- Downtown Streets Team work program

Key fields:

- `id`
- `name`
- `program_type`
- `operator_actor_id?`
- `status`
- `start_date?`
- `end_date?`

### Case

Use for litigation or other formal disputes that recur across records and decisions.

Examples:

- `Boyd v. City of San Rafael`
- `City of Grants Pass v. Johnson`

Key fields:

- `id`
- `name`
- `case_type`
- `court_name?`
- `filed_at?`
- `closed_at?`
- `status`

## Layer 2: Process And Decision Nodes

These capture what happened.

### Meeting

- `id`
- `institution_id`
- `starts_at`
- `meeting_type`
- `location_record_id?`
- `video_record_id?`

### AgendaItem

- `id`
- `meeting_id`
- `item_number?`
- `title`
- `summary?`
- `status?`

### Decision

Use for formal outcomes and actions.

Subtypes:

- ordinance_introduction
- ordinance_adoption
- resolution_adoption
- appropriation
- contract_authorization
- litigation_position
- policy_change

Key fields:

- `id`
- `decision_type`
- `institution_id`
- `meeting_id?`
- `agenda_item_id?`
- `title`
- `status`
- `decided_at?`
- `effective_date?`

### VoteCast

Use for individual member votes.

- `id`
- `decision_id`
- `actor_id?`
- `seat_id?`
- `vote`
- `sequence?`

### PublicComment

Use for meeting comments, letters, or public submissions tied to process.

- `id`
- `meeting_id?`
- `agenda_item_id?`
- `record_id?`
- `speaker_name_raw`
- `speaker_actor_id?`
- `self_identified_actor_id?`
- `stance?`
- `summary?`

### Appointment

Use for one actor occupying one seat for a bounded time period.

- `id`
- `actor_id`
- `seat_id`
- `appointed_by_actor_id?`
- `appointed_by_institution_id?`
- `started_at`
- `ended_at?`

### Membership

Use for board seats, staff roles, treasurers, executives, and other affiliations.

- `id`
- `actor_id`
- `organization_actor_id`
- `role`
- `started_at?`
- `ended_at?`

### MoneyFlow

Use for money movement or obligation.

Subtypes:

- contribution
- independent_expenditure
- grant_award
- appropriation
- contract_authorization
- payment
- behested_payment

Key fields:

- `id`
- `money_type`
- `amount`
- `currency`
- `date?`
- `from_actor_id?`
- `to_actor_id?`
- `from_institution_id?`
- `to_institution_id?`
- `decision_id?`
- `program_id?`

### CaseParticipation

Use for party and counsel roles in a case.

- `id`
- `case_id`
- `actor_id?`
- `institution_id?`
- `role`
- `started_at?`
- `ended_at?`

## Layer 3: Record And Evidence Nodes

These are the source artifacts.

### Record

This is the core evidence node.

Subclasses:

- `meeting_record`
- `legislative_record`
- `media_record`
- `financial_record`
- `contract_record`
- `legal_record`
- `program_record`

Key fields:

- `id`
- `record_class`
- `record_type`
- `title`
- `publisher`
- `published_at?`
- `source_url?`
- `source_tier`
- `artifact_paths[]`
- `text_path?`
- `status`

Recommended status values:

- `citation_only`
- `raw_capture`
- `text_extracted`
- `normalized`
- `duplicate`

### RecordSegment

Use when a larger record contains operationally important child records or bounded sections.

Examples:

- ordinance pages inside a packet
- contract exhibit inside a resolution bundle
- quote block inside an article
- public correspondence section inside a report

Key fields:

- `id`
- `record_id`
- `segment_type`
- `title?`
- `page_start?`
- `page_end?`
- `char_start?`
- `char_end?`
- `text_path?`

Rule:

- use `RecordSegment` when the parent record still matters
- promote the segment to its own `Record` when users will browse or link to it directly

The August 19 item `5.a` split is the first live example of this promotion pattern.

## Layer 4: Extraction And Review Nodes

These capture what the system thinks it found before or while promoting facts.

### Mention

Use for a named thing found in a record.

Examples:

- a quoted person in Marin IJ
- an organization named in a staff report
- a place named in minutes

Key fields:

- `id`
- `record_id`
- `segment_id?`
- `mention_type`
- `name_raw`
- `actor_id?`
- `institution_id?`
- `place_id?`
- `issue_id?`
- `role_label?`
- `affiliation_label?`
- `quote_excerpt?`
- `confidence`

Rule:

- `Mention` preserves source framing
- canonical resolution can happen later
- older notes may still say `ArticleMention`; treat that as a media-specific `Mention`

### Claim

Use for a candidate assertion that may or may not be promoted.

Examples:

- actor is affiliated with organization
- decision authorized contract amount
- article framed actor as resident
- record duplicates another record

Key fields:

- `id`
- `claim_type`
- `subject_node_id`
- `object_node_id?`
- `value_text?`
- `value_number?`
- `status`
- `confidence`
- `derived_from_record_id`
- `derived_from_segment_id?`

Recommended status values:

- `candidate`
- `promoted`
- `rejected`
- `needs_review`

### Lead

Use for pointers that are useful for research but too weak for the main graph.

Examples:

- anecdote from user
- social-media tip
- suspicious but uncorroborated NGO affiliation lead

## Direct Edges Vs Event Nodes

Do not store everything as a direct edge.

Use event nodes when the relationship needs:

- date
- amount
- role
- confidence
- source evidence

Examples:

- `Contribution` should be a `MoneyFlow`, not just `actor DONATED_TO actor`
- board service should be a `Membership`, not just `actor MEMBER_OF actor`
- officeholding should be an `Appointment`, not just `actor HOLDS seat`

Use direct edges for simpler structure:

- institution `PARENT_OF` institution
- seat `BELONGS_TO` institution
- meeting `PART_OF` institution
- agenda_item `PART_OF` meeting
- decision `ABOUT` issue
- decision `AFFECTS` place
- record `ATTACHED_TO` record
- record `FOR_EVENT` meeting

## Materialized Convenience Edges

Some edges can be derived and cached for query speed.

Examples:

- actor `CURRENT_MEMBER_OF` organization
- actor `CURRENTLY_HOLDS` seat
- program `OPERATES_AT` place
- actor `RECURS_ON` issue

These are views, not primary truth.

The primary truth should still live in:

- `Appointment`
- `Membership`
- `MoneyFlow`
- `PublicComment`
- `Record`
- `Claim`

## Record Ingestion Patterns

### Meeting Minutes

Typical outputs:

- one `Record` for the minutes
- one `Meeting`
- zero or more `AgendaItem`
- zero or more `Decision`
- zero or more `VoteCast`
- zero or more `PublicComment`
- supporting `Claim` nodes where the minutes are ambiguous

Typical relationship chain:

- minutes record `record_memorializes_decision` decision
- minutes record `record_for_event` meeting
- meeting `CONTAINS` agenda item
- decision `PART_OF` agenda item

### Ordinance Or Resolution

Typical outputs:

- one `Record` for the ordinance or resolution text
- optional `RecordSegment` if it lives inside a packet first
- one or more `Decision`
- optional `MoneyFlow`
- child `Record` nodes for contracts, exhibits, site plans, or attachments

Typical relationship chain:

- staff report `record_introduces_decision` ordinance introduction
- minutes `record_memorializes_decision` adoption
- resolution record `record_authorizes_decision` contract authorization
- contract record `record_attached_to_record` resolution record

### Marin IJ Article

Typical outputs:

- one `Record` for the article
- zero or more `Mention`
- zero or more `Claim`
- zero promoted affiliation facts unless explicit or corroborated

Typical relationship chain:

- article record `record_reports_on_event` meeting
- article record `record_reports_on_decision` decision
- mention preserves `role_label` and `affiliation_label` exactly as printed
- claim compares article framing against other records

## Promotion Rules

Promotion should be conservative.

Safe to promote directly from strong records:

- vote results from adopted minutes
- contract amount from signed contract or adopted resolution
- ordinance number from ordinance text
- named speaker from signed letter or speaker card

Usually keep as `Claim` first:

- inferred actor identity from a common name
- affiliation not explicit in the source
- article framing gap
- duplicate detection that has not been hash-confirmed

## Recommended Core Query Surfaces

The graph should support these first:

- actor -> records, comments, money, memberships, mentions
- issue -> decisions, meetings, records, places, recurring actors
- decision -> supporting records, votes, money, related program, affected place
- record -> what it says, what it attaches to, what claims came from it
- place -> which decisions, records, and programs touched it

## Immediate Design Implications

Three concrete implications follow:

1. The graph needs both `Record` and `Claim`.
2. Meeting minutes, resolutions, and articles should all feed the same record-centric model.
3. Full text stays outside the graph, but every graph object should be traceable back to a record or segment.
