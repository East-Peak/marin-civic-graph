# Criminal Justice Submodel

Date drafted: April 10, 2026

This document defines the first criminal-justice extension for Marin Civic Graph.

The goal is to make public criminal-case process legible without pretending we have a complete court-data mirror.

## Scope

The first version should model:

- booking and custody events
- booked charges and filed charges
- case metadata
- hearings and proceedings
- judge assignment
- prosecutor and defense roles
- public dispositions and sentences

It should not assume first-pass access to:

- broad remote criminal PDF access
- sealed or confidential records
- juvenile records
- complete statewide case history

## Public Record Surfaces

The current planning assumption for Marin is:

- Marin Superior Court `ePortal` exposes case and calendar search
- Marin Superior Court offers records requests and in-person inspection for public court records
- Marin Sheriff exposes custody and booking-log information
- Marin Sheriff exposes warrant-related public information
- Marin Superior Court exposes judicial assignments and biographies

This means the graph should begin with index-level and event-level public records, not deep document-scraping assumptions.

## Core Graph Objects

### Case

Use the existing `Case` node with:

- `case_type = criminal_prosecution`

Recommended fields:

- `id`
- `name`
- `case_type`
- `court_name`
- `court_institution_id?`
- `docket_number?`
- `status`
- `filed_at?`
- `closed_at?`

### Proceeding

A bounded criminal court event inside a case.

Examples:

- arraignment
- bail review
- pretrial conference
- readiness conference
- preliminary hearing
- plea hearing
- sentencing hearing
- probation review

Key fields:

- `id`
- `case_id`
- `proceeding_type`
- `scheduled_at?`
- `occurred_at?`
- `courtroom?`
- `judge_actor_id?`
- `status`

### Charge

A charge attached to a criminal case.

Important distinction:

- booked charge
- filed charge
- amended charge
- disposition charge

Key fields:

- `id`
- `case_id`
- `charge_stage`
- `statute_code?`
- `statute_text?`
- `description`
- `severity`
- `count_number?`
- `filed_at?`
- `disposed_at?`
- `status`

Suggested `charge_stage` values:

- `booking`
- `filed`
- `amended`
- `sentencing`

Suggested `severity` values:

- `infraction`
- `misdemeanor`
- `felony`
- `wobbler`
- `enhancement`

### CustodyEvent

A jail or custody state change tied to a defendant.

Examples:

- arrest booking
- jail admission
- transfer
- release on bail
- release on own recognizance
- hold
- remand

Key fields:

- `id`
- `actor_id`
- `case_id?`
- `custody_event_type`
- `occurred_at`
- `facility_place_id?`
- `booking_number?`
- `bail_amount?`
- `status?`

### ReleaseDecision

A court or custody outcome on whether a person remains detained or is released.

Examples:

- bail set
- bail denied
- released on own recognizance
- supervised release
- remanded

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

An attorney role in a case or proceeding.

Examples:

- district attorney
- deputy district attorney
- public defender
- appointed defense counsel
- private defense counsel

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

The outcome of a case or of a specific charge.

Examples:

- dismissed
- diversion
- plea
- convicted
- acquitted
- no complaint filed

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

The punishment or supervision outcome following conviction or plea.

Examples:

- county jail term
- prison term
- probation
- time served
- fine
- restitution
- diversion conditions

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

## Supporting Record Types

Use existing `Record` nodes with `record_class = legal_record`.

Priority `record_type` values:

- `booking_log_entry`
- `warrant_entry`
- `case_index_record`
- `calendar_entry`
- `register_of_actions`
- `criminal_complaint`
- `information`
- `minute_order`
- `plea_form`
- `judgment`
- `sentencing_order`
- `probation_order`

Not every case will have every record type available remotely.

## Key Joins

The minimum criminal chain should look like:

- defendant `Actor` -> `Case`
- `Case` -> `Charge`
- defendant `Actor` -> `CustodyEvent`
- `Proceeding` -> `Case`
- judge `Actor` -> `Proceeding`
- attorney `Actor` -> `AttorneyRepresentation`
- `Disposition` -> `Case` and optionally `Charge`
- `Sentence` -> `Disposition`
- all of the above -> `Record` evidence

## Modeling Rules

### Rule 1

Do not collapse booked charges and filed charges into one object.

### Rule 2

Do not infer judge behavior from one case.

### Rule 3

Keep event-level facts separate from downstream evaluation.

### Rule 4

Track attorney roles as explicit representations, not just loose mentions.

### Rule 5

Exclude sealed, juvenile, and confidential case material by default.

## First Useful Queries

- show all public proceedings for one criminal case
- show which judge presided over each proceeding
- show booked charges versus filed charges versus final dispositions
- show defense and prosecution roles by case
- show release decisions and later dispositions where the public record supports the join

## Minimum Viable Sample

The first criminal sample should prove the submodel on one small basket of public cases.

A minimum usable basket would include:

- one booking-log-visible defendant
- one linked criminal case
- several calendar or proceeding entries
- judge assignment
- attorney roles where visible
- one disposition or sentence outcome

That is enough to test the graph without overpromising coverage.
