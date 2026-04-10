# Permit Layer Ingestion Checklist

Date drafted: April 10, 2026

This checklist turns the permit-layer planning docs into an execution sequence.

## Goal

Produce one small but real permit-thread sample basket that pressure-tests:

- `Project`
- `Application`
- `Determination`
- `Permit`
- `Condition`
- `Appeal`
- `Record` with `administrative_record`

## Phase 1: Capture Discovery Surfaces

Capture and manifest these official pages first:

- Marin County Planning landing page
- Marin County Get a Planning Permit
- Marin County Planning applications under review
- Marin County Planning Division forms
- Marin County Planning Commission hearings
- Marin County Deputy Zoning Administrator hearings
- San Rafael Apply to Planning Online
- San Rafael OpenGov planning category
- San Rafael Major Planning Projects
- San Rafael Planning Commission meetings
- San Rafael Zoning Administrator hearings

Minimum output:

- raw HTML captures
- manifests
- source registry entries confirmed against live behavior

## Phase 2: Pick Three Sample Threads

### Slot A: San Rafael project thread

Select one project from:

- Major Planning Projects
- Planning Commission meetings
- Zoning Administrator hearings

Minimum usable outcome:

- one `Project`
- one `Place`
- one hearing `Meeting`
- one or more `Record` nodes

### Slot B: Marin County active application

Select one application from:

- Planning applications under review
- Deputy Zoning Administrator or Planning Commission hearing lists

Minimum usable outcome:

- one `Project`
- one `Application`
- one `Place`
- one discovery `Record`

### Slot C: appealed or denied thread

Select one project where the public record shows:

- denial
- approval with conditions that triggered appeal
- appeal filing
- appeal hearing

Minimum usable outcome:

- one `Determination`
- one `Appeal`
- one `Decision` or equivalent outcome
- supporting `Record` nodes

## Phase 3: Normalize Objects

For each selected thread, produce:

- `project-*.json`
- `application-*.json`
- `determination-*.json`
- `permit-*.json` where warranted
- `condition-*.json` where warranted
- `appeal-*.json` where warranted
- `record-*.json`

Required joins:

- `project.primary_place_id`
- `application.project_id`
- `determination.project_id`
- `determination.application_id`
- `permit.project_id`
- `appeal.project_id`
- `appeal.from_determination_id`

## Phase 4: Evidence Checks

Do not promote a permit-layer fact unless the record supports it clearly.

Safe early promotions:

- application number
- applicant name as printed
- project name as printed
- hearing date and body
- approval / denial status from adopted minutes or signed determination
- conditions explicitly listed in a determination or permit document

Keep as `Claim` first:

- inferred parcel matches
- inferred corporate affiliate relationships
- inferred permit issuance where only an application is visible
- implied appeal rights without an actual appeal filing

## Phase 5: Review For Model Stress

At the end of the first three samples, answer:

- was `Project` necessary and stable?
- did `Determination` add value beyond `Decision`?
- did `Permit` stay distinct from `Application` in the public record?
- were conditions common enough to justify first-class nodes?
- did appeals behave more like administrative filings or more like full meeting agenda items?

## Stop Conditions

Pause and revise the model if:

- the same project cannot be linked across records without hand-wavy matching
- the public record rarely distinguishes application from permit
- determinations and decisions collapse into the same object in practice
- the OpenGov portal blocks stable capture badly enough that the model needs a city-specific workaround
