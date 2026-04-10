# Schema v1

The schema should stay small and composable.

## Core Principle

Store concrete events and records.

Do not store "influence" as a primitive fact. Derive it later from observable data.

## Core Node Types

### Actor

Represents:

- person
- nonprofit
- business
- PAC
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

### MoneyFlow

Represents:

- campaign contribution
- independent expenditure
- contract payment
- grant
- behested payment

Key fields:

- `id`
- `money_type`
- `amount`
- `date`
- `from_actor_id?`
- `to_actor_id?`
- `related_decision_id?`
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
- Form 460
- Form 700
- Form 803
- 990

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

Examples:

- Marin IJ article = `media_record`
- ordinance or resolution = `legislative_record`
- minutes or packet = `meeting_record`
- Form 460 / 700 / 803 / 990 = `financial_record`

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

### Place

Represents:

- jurisdiction
- district
- facility
- park
- corridor
- address cluster

Key fields:

- `id`
- `name`
- `place_type`
- `jurisdiction_id?`
- `lat?`
- `lon?`

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

- `id`
- `actor_id`
- `seat_id`
- `appointed_by_actor_id?`
- `appointed_at`
- `ended_at?`

### Membership

- `id`
- `actor_id`
- `organization_id`
- `role`
- `start_date?`
- `end_date?`

### CaseParticipation

- `id`
- `case_name`
- `actor_id`
- `role`
- `date?`

### ArticleMention

- `id`
- `record_id`
- `actor_id?`
- `name_raw`
- `role_label?`
- `affiliation_label?`
- `quote_excerpt?`
- `mention_type`
- `confidence`

## Core Relationships

- actor `HOLDS` seat
- seat `BELONGS_TO` institution
- institution `HOLDS` meeting
- meeting `CONTAINS` agenda_item
- agenda_item `RESULTS_IN` decision
- decision `ABOUT` issue
- decision `AFFECTS` place
- document `EVIDENCES` meeting / agenda_item / decision / money_flow / comment
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
