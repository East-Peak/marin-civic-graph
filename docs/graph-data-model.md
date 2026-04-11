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

- canonical entities like actors, institutions, seats, elections, committees, places, projects, issues, programs, and cases
- process entities like meetings, agenda items, decisions, candidacies, filings, economic-interest disclosures, applications, permits, determinations, conditions, appeals, votes, comments, appointments, memberships, money flows, proceedings, charges, custody events, release decisions, dispositions, and sentences
- record nodes for ordinances, minutes, articles, contracts, packets, applications, determinations, and campaign or disclosure filings
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
- political organization
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

### Election

Use for one contest context tied to a date and jurisdiction.

Examples:

- one city-council election
- one supervisor district election

Key fields:

- `id`
- `jurisdiction_place_id`
- `election_type`
- `election_date`
- `cycle_label?`
- `seat_id?`
- `status`

### Committee

Use for a regulated filing entity in campaign-finance and disclosure workflows.

Examples:

- candidate-controlled committee
- officeholder committee
- independent-expenditure committee
- ballot-measure committee

Key fields:

- `id`
- `name`
- `committee_type`
- `fppc_id?`
- `jurisdiction_place_id?`
- `controlling_actor_id?`
- `sponsored_by_actor_id?`
- `treasurer_actor_id?`
- `primary_election_id?`
- `status`

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
- parcel
- site

### Project

Use for a durable proposal, site-specific thread, or capital concept that persists across one or more applications, determinations, permits, appeals, meetings, or cases.

Examples:

- one housing project
- one use-permit renewal thread
- one shelter site proposal
- one road-diet or streetscape redesign

Key fields:

- `id`
- `project_type`
- `name`
- `primary_place_id`
- `jurisdiction_place_id`
- `applicant_actor_id?`
- `status`
- `source_system_ref?`

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
- one Marin felony prosecution

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
- permit_approval
- permit_denial
- appeal_decision
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

### Application

Use for a filed request that starts or extends a project review thread.

Examples:

- planning permit application
- use permit amendment
- design review application
- petition for appeal

Key fields:

- `id`
- `project_id`
- `institution_id`
- `application_type`
- `application_number?`
- `applicant_actor_id?`
- `filed_at?`
- `deemed_complete_at?`
- `status`
- `parent_application_id?`

### Permit

Use for a specific entitlement, permit, or authorization attached to a project.

Examples:

- coastal development permit
- use permit
- sign permit
- tree removal permit

Key fields:

- `id`
- `project_id`
- `application_id?`
- `institution_id`
- `permit_type`
- `permit_number?`
- `status`
- `issued_at?`
- `expires_at?`
- `discretionary?`

### Determination

Use for a planning or administrative outcome that may or may not coincide with a meeting vote.

Examples:

- application deemed incomplete
- CEQA exemption determination
- approval with conditions
- denial letter
- continuation pending revisions

Key fields:

- `id`
- `project_id`
- `application_id?`
- `institution_id`
- `determination_type`
- `status`
- `decided_at?`
- `related_decision_id?`
- `appeal_deadline_at?`

### Condition

Use for one requirement attached to a project outcome.

Examples:

- landscaping requirement
- hours-of-operation limit
- mitigation monitoring condition
- design revision requirement

Key fields:

- `id`
- `project_id`
- `determination_id?`
- `permit_id?`
- `condition_number?`
- `condition_type`
- `text`
- `status`
- `due_at?`

### Appeal

Use for a challenge to a permit or determination.

Examples:

- neighborhood appeal of approval
- applicant appeal of denial
- board appeal of zoning administrator decision

Key fields:

- `id`
- `project_id`
- `from_determination_id?`
- `from_permit_id?`
- `appellant_actor_id?`
- `institution_id`
- `filed_at?`
- `status`
- `hearing_meeting_id?`
- `outcome_decision_id?`

### Procurement

Use for a bounded public solicitation or vendor-selection process.

Examples:

- request for proposals
- request for qualifications
- invitation for bids
- emergency procurement

Key fields:

- `id`
- `institution_id`
- `procurement_type`
- `title`
- `solicitation_number?`
- `procurement_method?`
- `status`
- `issued_at?`
- `due_at?`
- `project_id?`
- `program_id?`

### Agreement

Use for the ongoing contractual or grant relationship, not just the approval vote or the PDF itself.

Examples:

- professional services agreement
- public works contract
- grant agreement
- on-call consultant agreement
- memorandum of understanding

Key fields:

- `id`
- `institution_id`
- `counterparty_actor_id`
- `agreement_type`
- `agreement_number?`
- `procurement_id?`
- `project_id?`
- `program_id?`
- `status`
- `effective_start?`
- `effective_end?`
- `not_to_exceed_amount?`

### Amendment

Use for one bounded change to an agreement.

Examples:

- amount increase
- scope change
- term extension
- no-cost extension

Key fields:

- `id`
- `agreement_id`
- `amendment_type`
- `sequence_number?`
- `status`
- `decided_at?`
- `effective_date?`
- `delta_amount?`
- `new_total_amount?`
- `term_extended_to?`

### Deliverable

Use for one promised output or reporting milestone under an agreement or funded program.

Examples:

- annual work plan
- quarterly progress report
- reimbursement request
- outreach milestone

Key fields:

- `id`
- `agreement_id?`
- `program_id?`
- `deliverable_type`
- `title`
- `due_at?`
- `submitted_at?`
- `status`

### PerformanceReview

Use for public evaluation, compliance, or monitoring objects tied to agreements or programs.

Examples:

- single audit finding
- recovery-plan performance report
- subrecipient compliance review
- board update on contracted outcomes

Key fields:

- `id`
- `agreement_id?`
- `program_id?`
- `review_type`
- `period_start?`
- `period_end?`
- `status`
- `summary?`

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

### Candidacy

Use for one actor running for or holding one seat in one election cycle.

- `id`
- `candidate_actor_id`
- `seat_id`
- `election_id`
- `committee_id?`
- `incumbency_status?`
- `declaration_filed_at?`
- `qualified_at?`
- `result_status?`

### Filing

Use for one filed campaign or disclosure report.

Examples:

- Form 460
- Form 496
- Form 497
- Form 501
- local clerk-hosted filing export

Key fields:

- `id`
- `filing_type`
- `committee_id?`
- `filer_actor_id?`
- `filing_institution_id?`
- `election_id?`
- `period_start?`
- `period_end?`
- `filed_at`
- `amended_filing_id?`
- `status`

### EconomicInterestDisclosure

Use for a structured Statement of Economic Interests object backed by a filing record.

Examples:

- annual Form 700
- assuming-office Form 700
- leaving-office Form 700
- candidate Form 700

Key fields:

- `id`
- `filer_actor_id`
- `filing_institution_id`
- `seat_id?`
- `disclosure_type`
- `covering_period_start?`
- `covering_period_end?`
- `filed_at`
- `status`

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
- `from_committee_id?`
- `to_committee_id?`
- `beneficiary_actor_id?`
- `from_institution_id?`
- `to_institution_id?`
- `decision_id?`
- `agreement_id?`
- `amendment_id?`
- `program_id?`
- `filing_id?`
- `election_id?`
- `support_oppose?`

### CaseParticipation

Use for party and counsel roles in a case.

- `id`
- `case_id`
- `actor_id?`
- `institution_id?`
- `role`
- `started_at?`
- `ended_at?`

### Proceeding

Use for bounded court events inside a case.

Examples:

- arraignment
- bail review
- plea hearing
- sentencing hearing
- probation review

Key fields:

- `id`
- `case_id`
- `proceeding_type`
- `scheduled_at?`
- `occurred_at?`
- `judge_actor_id?`
- `status`

### Charge

Use for criminal charges attached to a criminal prosecution.

Important distinction:

- booked charge
- filed charge
- amended charge
- final disposition charge

Key fields:

- `id`
- `case_id`
- `charge_stage`
- `statute_code?`
- `description`
- `severity`
- `count_number?`
- `status`

### CustodyEvent

Use for arrest, booking, jail admission, release, remand, and transfer events.

Key fields:

- `id`
- `actor_id`
- `case_id?`
- `custody_event_type`
- `occurred_at`
- `facility_place_id?`
- `booking_number?`
- `bail_amount?`

### ReleaseDecision

Use for detention and release outcomes.

Examples:

- bail set
- own recognizance release
- supervised release
- remand

Key fields:

- `id`
- `case_id`
- `proceeding_id?`
- `actor_id`
- `judge_actor_id?`
- `release_type`
- `amount?`
- `decided_at`
- `conditions_text?`

### AttorneyRepresentation

Use for prosecutor and defense roles in a case or proceeding.

Key fields:

- `id`
- `case_id`
- `proceeding_id?`
- `actor_id`
- `client_actor_id?`
- `organization_actor_id?`
- `representation_role`
- `started_at?`
- `ended_at?`

### Disposition

Use for the outcome of a case or charge.

Examples:

- dismissed
- plea
- convicted
- acquitted
- diversion

Key fields:

- `id`
- `case_id`
- `charge_id?`
- `proceeding_id?`
- `disposition_type`
- `disposition_date`
- `judge_actor_id?`
- `notes?`

### Sentence

Use for punishment or supervision outcomes following disposition.

Examples:

- jail term
- prison term
- probation
- fine
- restitution
- time served

Key fields:

- `id`
- `case_id`
- `charge_id?`
- `disposition_id?`
- `sentence_type`
- `imposed_at`
- `duration_text?`
- `amount?`
- `conditions_text?`

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
- `administrative_record`

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

### Planning Application Or Permit Thread

Typical outputs:

- one `Project`
- one or more `Application`
- zero or more `Record` nodes for application forms, completeness letters, hearing notices, staff reports, determination letters, permit cards, and appeal filings
- zero or more `Determination`
- zero or more `Condition`
- zero or more `Permit`
- zero or more `Appeal`
- optional `Meeting` or `Proceeding`
- optional `Decision`
- optional `Case`

Typical relationship chain:

- application record `record_describes_project` project
- application record `record_starts_process` application
- application `FOR_PROJECT` project
- hearing notice `record_for_event` meeting or proceeding
- staff report `record_introduces_decision` determination or decision
- determination `FOR_APPLICATION` application
- permit `FOR_PROJECT` project
- appeal `CHALLENGES` determination
- appeal decision `FOR_PROJECT` project
- case `ABOUT` project if litigated

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

### Criminal Case Public Surface

Typical outputs:

- one `Case` with `case_type = criminal_prosecution`
- zero or more `Charge`
- zero or more `CustodyEvent`
- zero or more `Proceeding`
- zero or more `ReleaseDecision`
- zero or more `AttorneyRepresentation`
- zero or more `Disposition`
- zero or more `Sentence`
- one or more `Record` nodes for booking logs, case-index records, calendar entries, minute orders, or judgments
- `Claim` nodes where booked charges, filed charges, and final outcomes cannot yet be cleanly matched

The key rule is to preserve stage differences rather than flattening everything into one case summary.

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
- project -> applications, permits, determinations, appeals, records, places
- issue -> decisions, meetings, records, places, recurring actors
- decision -> supporting records, votes, money, related program, affected place
- record -> what it says, what it attaches to, what claims came from it
- place -> which decisions, records, and programs touched it

## Immediate Design Implications

Three concrete implications follow:

1. The graph needs both `Record` and `Claim`.
2. Meeting minutes, resolutions, and articles should all feed the same record-centric model.
3. Full text stays outside the graph, but every graph object should be traceable back to a record or segment.
