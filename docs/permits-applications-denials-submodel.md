# Permits, Applications, And Denials Submodel

Date drafted: April 10, 2026

This document defines the first permit-layer node set for Marin Civic Graph.

The goal is to make project-level administrative process legible without pretending every permit thread looks like a city-council vote.

## Why This Layer Matters

- many important local fights never become headline council items
- housing, shelters, business restrictions, design changes, and neighborhood conflicts often get decided here first
- the project needs a way to model site-specific threads that cross applications, staff review, hearings, determinations, permits, appeals, and litigation

## Core Decision

Formalize the permit layer around one durable context node plus five process nodes:

- `Project`
- `Application`
- `Permit`
- `Determination`
- `Condition`
- `Appeal`

Use `Record` with `record_class = administrative_record` for the evidence surfaces that drive these objects.

## Canonical Context Node

### Project

Use `Project` for a real-world proposal or site-specific thread that persists across records and process steps.

Examples:

- one housing development
- one shelter site
- one restaurant expansion
- one streetscape redesign
- one use-permit renewal

Key fields:

- `id`
- `name`
- `project_type`
- `primary_place_id`
- `jurisdiction_id`
- `applicant_actor_id?`
- `status`
- `source_system_ref?`

Rule:

- `Project` is not just a parcel and not just an application
- use it when the same proposal recurs across multiple records or decisions

## Process Nodes

### Application

Represents a filed request for review.

Examples:

- planning permit application
- amendment application
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

Represents an entitlement, authorization, or permit tied to a project.

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

Rule:

- do not create a `Permit` just because an application asks for one
- create it when the record clearly identifies a permit object or issuance state

### Determination

Represents an administrative or quasi-judicial outcome on an application.

Examples:

- completeness determination
- approval
- approval with conditions
- denial
- CEQA exemption determination
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

Rule:

- `Determination` is the domain-specific outcome object
- link it to `Decision` when there is also a formal vote or appeal ruling

### Condition

Represents one bounded obligation, restriction, or mitigation attached to a determination or permit.

Examples:

- hours-of-operation limit
- landscaping requirement
- design revision requirement
- mitigation monitoring condition

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

Represents a challenge to a determination or permit.

Examples:

- neighbor appeal of approval
- applicant appeal of denial
- planning commission appeal of staff or zoning administrator action

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

## Evidence Model

Use `Record` with `record_class = administrative_record` for:

- application forms
- application checklists
- completeness letters
- hearing notices
- staff reports
- determination letters
- conditions of approval
- denial letters
- appeal petitions
- permit cards
- project status pages

Two important notes:

- hearing packets and minutes can still be `meeting_record` when they belong to a public-hearing body
- adopted resolutions or ordinances that decide an appeal remain `legislative_record`

## Join Pattern

The basic chain is:

```text
Actor -> Application -> Project -> Determination -> Permit
                                 -> Appeal -> Decision
Project -> Place
Project -> Record
Project -> Case
```

Common joins:

- applicant `Actor`
- project site `Place`
- reviewing `Institution`
- hearing `Meeting` or `Proceeding`
- resulting `Decision`
- related `Case` if litigated
- issue tags via `Issue`

Parcel and address data should usually remain `Place` subtypes rather than a separate top-level parcel node for v1.

## Worked Flow

A typical thread can look like this:

1. A planning application is filed for a project.
2. Staff issues a completeness letter or requests revisions.
3. A hearing notice and staff report are published.
4. A zoning administrator or planning commission hearing occurs.
5. A determination is issued: approval, denial, or approval with conditions.
6. One or more permits or entitlements are issued.
7. An appeal may be filed and heard by a higher body.
8. Litigation may later challenge the same project or permit thread.

That means one project can touch:

- `Record`
- `Meeting`
- `Decision`
- `Application`
- `Permit`
- `Determination`
- `Condition`
- `Appeal`
- `Case`

## Initial Scope Boundaries

Start with planning and land-use style administrative surfaces:

- city planning applications
- county planning applications
- zoning administrator hearings
- planning commission hearings
- appeal filings and appeal decisions

Do not expand v1 to everything that says "permit."

Keep these adjacent surfaces for later:

- building permits
- fire permits
- encroachment permits
- business licensing
- code-enforcement abatement
- full CEQA object model

## First Pressure-Test Shape

The first useful sample basket should include:

- one San Rafael major planning project
- one Marin County application under review
- one appealed or denied project thread

That is enough to pressure-test:

- `Project` identity
- application numbering
- hearing joins
- determination versus decision
- appeal layering
- project-to-place joins

## Official Source Surfaces

Official pages confirmed on April 10, 2026:

- Marin County Planning landing page: https://www.marincounty.gov/departments/cda/planning
- Marin County Get a Planning Permit: https://www.marincounty.gov/departments/cda/planning/planning-permits
- Marin County Planning applications under review: https://www.marincounty.gov/departments/cda/planning/projects
- Marin County Planning Commission hearings: https://www.marincounty.gov/departments/cda/planning/boards-commissions-and-public-hearings/planning-commission-hearings
- Marin County Deputy Zoning Administrator hearings: https://www.marincounty.gov/departments/cda/planning/boards-commissions-and-public-hearings/deputy-zoning-administrator-hearings
- Marin County Planning Division forms: https://www.marincounty.gov/departments/cda/planning/planning-permits/planning-division-forms
- San Rafael Apply to Planning Online: https://www.cityofsanrafael.org/apply-to-planning-online/
- San Rafael Major Planning Projects 2025: https://www.cityofsanrafael.org/major-planning-projects-2025/
- San Rafael Planning Commission meetings: https://www.cityofsanrafael.org/planning-commission-meetings/
- San Rafael Zoning Administrator hearings: https://www.cityofsanrafael.org/zoning-administrator-hearings/

## Revisit If

- parcel-level work becomes central enough to justify a first-class parcel node
- CEQA review becomes common enough to deserve `EnvironmentalReview` as a top-level object
- building / fire / public-works permit systems need to be folded into the same administrative layer
