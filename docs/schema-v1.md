# Schema v1

The schema should stay small and composable.

This is the compact summary.

For the layered version of what belongs in the graph database, see [Graph Data Model](./graph-data-model.md).

## Core Principle

Store concrete events and records.

Do not store "influence" as a primitive fact. Derive it later from observable data.

## Core Node Types

### Actor

Represents:

- person
- nonprofit
- business
- political organization
- law firm
- union
- media outlet

Key fields:

- `id`
- `name`
- `actor_type`
- `aliases[]`
- `website`
- `jurisdiction_ids[]`

### Institution

Represents:

- city council
- county board
- department
- commission
- advisory body
- court

Key fields:

- `id`
- `name`
- `institution_type`
- `jurisdiction_id`
- `parent_institution_id?`
- `official_url`
- `legal_basis_url?`

### Seat

Represents an elected or appointed seat attached to an institution.

Key fields:

- `id`
- `institution_id`
- `name`
- `seat_type`
- `district?`
- `appointing_authority?`

### SeatService

Represents one actor occupying one seat for a bounded or observed period.

Key fields:

- `id`
- `actor_id`
- `seat_id`
- `service_type`
- `institution_id?`
- `election_id?`
- `candidacy_id?`
- `appointment_id?`
- `started_at?`
- `ended_at?`
- `observed_at?`
- `status`

### Election

Represents a bounded contest for a seat, office, or measure.

Key fields:

- `id`
- `jurisdiction_id`
- `election_type`
- `election_date`
- `cycle_label?`
- `seat_id?`
- `status`

### Committee

Represents a regulated campaign-finance entity.

Key fields:

- `id`
- `name`
- `committee_type`
- `fppc_id?`
- `jurisdiction_id?`
- `controlling_actor_id?`
- `sponsored_by_actor_id?`
- `treasurer_actor_id?`
- `primary_election_id?`
- `status`

### Meeting

Key fields:

- `id`
- `institution_id`
- `starts_at`
- `meeting_type`
- `agenda_url`
- `minutes_url?`
- `video_url?`

### AgendaItem

Key fields:

- `id`
- `meeting_id`
- `title`
- `item_number?`
- `summary`
- `issue_ids[]`
- `place_ids[]`

### Decision

Represents:

- vote
- ordinance adoption
- resolution
- contract award
- grant approval
- litigation stance
- enforcement-policy change

Key fields:

- `id`
- `decision_type`
- `institution_id`
- `meeting_id?`
- `agenda_item_id?`
- `title`
- `status`
- `effective_date?`

### Candidacy

Represents one actor running for one seat in one election cycle.

Key fields:

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

Represents a structured campaign or disclosure filing object.

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

Represents a structured Statement of Economic Interests object.

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

### Procurement

Represents:

- request for proposals
- request for qualifications
- invitation for bids
- emergency procurement
- sole-source procurement

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

Represents:

- professional services agreement
- public works contract
- grant agreement
- subrecipient agreement
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

Represents:

- contract amendment
- grant amendment
- no-cost extension
- amount increase
- scope change

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

Represents:

- annual work plan
- quarterly report
- outreach milestone
- reimbursement request

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

Represents:

- single audit finding
- recovery-plan progress report
- program update
- compliance review

Key fields:

- `id`
- `agreement_id?`
- `program_id?`
- `review_type`
- `period_start?`
- `period_end?`
- `status`
- `summary?`

### MoneyFlow

Represents:

- campaign contribution
- campaign expenditure
- independent expenditure
- contract payment
- grant
- behested payment

Key fields:

- `id`
- `money_type`
- `amount`
- `currency?`
- `date`
- `from_actor_id?`
- `to_actor_id?`
- `from_committee_id?`
- `to_committee_id?`
- `beneficiary_actor_id?`
- `decision_id?`
- `agreement_id?`
- `amendment_id?`
- `filing_id?`
- `election_id?`
- `support_oppose?`
- `related_issue_ids[]`

### Record

Represents:

- ordinance
- resolution
- agenda
- packet
- minutes
- filing
- contract
- article
- application
- hearing notice
- determination letter
- Form 460
- Form 496
- Form 497
- Form 501
- Form 700
- Form 803
- 990
- booking log entry
- case index record
- calendar entry
- judgment

Key fields:

- `id`
- `record_class`
- `record_type`
- `title`
- `source_url`
- `publisher`
- `published_at?`
- `source_tier`
- `text_extracted?`

Suggested `record_class` values:

- `meeting_record`
- `legislative_record`
- `media_record`
- `financial_record`
- `contract_record`
- `legal_record`
- `program_record`
- `administrative_record`

Examples:

- Marin IJ article = `media_record`
- ordinance or resolution = `legislative_record`
- minutes or packet = `meeting_record`
- Form 460 / 496 / 497 / 501 / 700 / 803 / 990 = `financial_record`
- booking log entry or sentencing order = `legal_record`
- planning application, hearing notice, or appeal filing = `administrative_record`

Note:

- older planning notes may still say `Document`
- treat `Record` as the umbrella node and migrate older naming over time

### Issue

Represents:

- homelessness
- encampments
- parking
- traffic calming
- public safety
- housing

Key fields:

- `id`
- `name`
- `slug`
- `description?`

### Project

Represents a durable real-world proposal or site-specific thread that can outlive one application or hearing.

Examples:

- housing development proposal
- shelter site
- restaurant expansion
- street redesign
- coastal permit proposal

Key fields:

- `id`
- `name`
- `project_type`
- `primary_place_id`
- `jurisdiction_id`
- `applicant_actor_id?`
- `status`
- `source_system_ref?`

### Program

Represents:

- sanctioned camping program
- grant-funded initiative
- capital funding program
- work program
- outreach program
- shelter operation

Key fields:

- `id`
- `name`
- `program_type`
- `operator_actor_id?`
- `status`
- `start_date?`
- `end_date?`

### Case

Represents:

- lawsuit
- appeal
- enforcement dispute
- criminal prosecution

Key fields:

- `id`
- `name`
- `case_type`
- `court_name?`
- `status`
- `filed_at?`
- `closed_at?`

### Proceeding

Represents:

- hearing
- calendar event
- arraignment
- bail review
- plea hearing
- sentencing hearing

Key fields:

- `id`
- `case_id`
- `proceeding_type`
- `scheduled_at?`
- `occurred_at?`
- `judge_actor_id?`
- `status`

### Application

Represents a request submitted to a planning, permitting, or administrative review body.

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

Represents an issued or issuable entitlement, authorization, or permit tied to a project.

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

Represents an administrative or quasi-judicial outcome on an application.

Examples:

- completeness determination
- approval
- approval with conditions
- denial
- exemption determination
- continuation

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

Represents one bounded obligation, restriction, or mitigation attached to a determination or permit.

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

Represents a challenge to a permit or determination.

Key fields:

- `id`
- `project_id`
- `from_determination_id?`
- `from_permit_id?`
- `appellant_actor_id?`
- `institution_id`
- `filed_at?`
- `status`
- `outcome_decision_id?`
- `hearing_meeting_id?`

### Charge

Represents a criminal charge inside a case.

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

Represents:

- booking
- jail admission
- release
- remand
- transfer

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

Represents:

- bail set
- bail denied
- own-recognizance release
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

### AttorneyRepresentation

Represents a prosecutor or defense role in a case or proceeding.

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

Represents:

- dismissal
- plea
- conviction
- acquittal
- diversion

Key fields:

- `id`
- `case_id`
- `charge_id?`
- `proceeding_id?`
- `disposition_type`
- `disposition_date`
- `judge_actor_id?`

### Sentence

Represents:

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

### Place

Represents:

- jurisdiction
- district
- facility
- park
- corridor
- address cluster
- parcel
- site

Key fields:

- `id`
- `name`
- `place_type`
- `jurisdiction_id?`
- `lat?`
- `lon?`

### RecordSegment

Represents:

- ordinance pages split out of a packet
- contract exhibit inside a resolution bundle
- quoted section inside an article
- correspondence section inside a report

Key fields:

- `id`
- `record_id`
- `segment_type`
- `title?`
- `page_start?`
- `page_end?`
- `text_path?`

## Event Nodes

Make these first-class so they can carry date, role, confidence, and evidence.

### PublicComment

- `id`
- `meeting_id`
- `agenda_item_id?`
- `speaker_name_raw`
- `speaker_actor_id?`
- `affiliation_actor_id?`
- `stance`
- `summary`

### VoteCast

- `id`
- `decision_id`
- `seat_id?`
- `actor_id`
- `vote`

### Appointment

Represents an appointment action or appointment record that may create a later seat service.

- `id`
- `seat_id`
- `selected_actor_id`
- `appointed_by_actor_id?`
- `appointed_by_institution_id?`
- `appointed_at`
- `resulting_seat_service_id?`

### Membership

- `id`
- `actor_id`
- `organization_id`
- `role`
- `start_date?`
- `end_date?`

### CaseParticipation

- `id`
- `case_id`
- `actor_id?`
- `institution_id?`
- `role`
- `start_date?`
- `end_date?`

### Mention

- `id`
- `record_id`
- `segment_id?`
- `actor_id?`
- `institution_id?`
- `place_id?`
- `issue_id?`
- `name_raw`
- `role_label?`
- `affiliation_label?`
- `quote_excerpt?`
- `mention_type`
- `confidence`

### Claim

Represents a candidate assertion derived from one or more records.

Examples:

- actor affiliation
- duplicate record match
- article framing claim
- decision authorization claim

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

### Lead

Represents a useful but unverified pointer.

Examples:

- anecdote
- tip
- unresolved social-media assertion

## Core Relationships

- actor `HOLDS` seat
- seat `BELONGS_TO` institution
- institution `HOLDS` meeting
- meeting `CONTAINS` agenda_item
- agenda_item `RESULTS_IN` decision
- decision `ABOUT` issue
- decision `AFFECTS` place
- decision `IMPLEMENTS` program
- case `INVOLVES` actor / institution
- record `EVIDENCES` meeting / agenda_item / decision / money_flow / comment / claim
- record `ATTACHED_TO` record
- record_segment `PART_OF` record
- actor `MADE` public_comment
- actor `MADE` money_flow
- actor `RECEIVED` money_flow
- actor `MEMBER_OF` organization
- institution `HAS_JURISDICTION_OVER` place

## Evidence Tiers

### Tier A

- adopted minutes
- signed contracts
- campaign filings
- disclosure forms
- court dockets / opinions

### Tier B

- agendas
- packets
- meeting videos
- official webpages
- clerk records

### Tier C

- local media with concrete sourcing

### Tier D

- commentary / essays / secondary analysis

### Tier E

- anecdotal leads
- user tips

Only Tier A-C should promote a claim into the main graph.

## Example Queries

- Show all comments, votes, documents, and money flows around one issue in San Rafael.
- Show recurring actors across campaign giving, public comment, contracts, and grants.
- Show every decision that touched a specific park, corridor, or encampment site.
- Show all organizations that received public money and later appeared in related meetings.
- Show people quoted as ordinary residents in local media who also recur as activists, nonprofit staff, board members, donors, or public commenters.
