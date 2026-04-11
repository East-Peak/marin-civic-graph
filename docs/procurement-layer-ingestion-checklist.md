# Procurement Layer Ingestion Checklist

Date drafted: April 10, 2026

This checklist turns the procurement-layer planning docs into an execution sequence.

## Goal

Produce one small but real procurement sample basket that pressure-tests:

- `Procurement`
- `Agreement`
- `Amendment`
- `Deliverable`
- `PerformanceReview`
- `MoneyFlow`
- `Record` with `contract_record`, `financial_record`, and `program_record`

## Phase 1: Capture Discovery Surfaces

Capture and manifest these official pages first:

- Marin County `Contracting Opportunities`
- Marin County `Procurement Division`
- Marin County `Budget and Priority Setting`
- Marin County `How We Measure Success`
- Marin County `State and Local Fiscal Recovery Funds`
- Marin County Board of Supervisors meetings
- San Rafael `Bids and Proposals`
- San Rafael City Council meetings
- San Rafael `ACFR 2023`
- San Rafael `2023 Single Audit`

Minimum output:

- raw HTML or PDF captures
- manifests
- source registry entries confirmed against live behavior

## Phase 2: Pick Three Sample Threads

### Slot A: County solicitation to award

Select one county thread where the public record shows:

- solicitation
- eventual Board approval or delegated agreement

Minimum usable outcome:

- one `Procurement`
- one `Decision`
- one `Agreement`
- supporting `Record` nodes

### Slot B: City agreement with amendment or renewal

Select one city thread where the public record shows:

- initial award
- later amendment, extension, or added funding

Minimum usable outcome:

- one `Agreement`
- one `Amendment`
- one related `Decision`
- supporting `Record` nodes

### Slot C: Grant-funded or program-funded thread

Select one thread where the public record shows:

- funding allocation or grant acceptance
- implementation or service delivery
- later reporting, audit, or performance material

Minimum usable outcome:

- one `Program`
- one or more `MoneyFlow` objects
- one `PerformanceReview`
- supporting `Record` nodes

## Phase 3: Normalize Objects

For each selected thread, produce:

- `procurement-*.json`
- `agreement-*.json`
- `amendment-*.json`
- `deliverable-*.json` where warranted
- `performance-review-*.json` where warranted
- `moneyflow-*.json`
- `record-*.json`

Required joins:

- `procurement.institution_id`
- `agreement.institution_id`
- `agreement.counterparty_actor_id`
- `agreement.procurement_id?`
- `agreement.project_id?`
- `agreement.program_id?`
- `amendment.agreement_id`
- `deliverable.agreement_id?`
- `deliverable.program_id?`
- `performance_review.agreement_id?`
- `performance_review.program_id?`
- `money_flow.agreement_id?`
- `money_flow.decision_id?`

## Phase 4: Evidence Checks

Do not promote a procurement-layer fact unless the record supports it clearly.

Safe early promotions:

- solicitation title and due date
- public institution issuing the solicitation
- contract or grant amount stated in an approval record
- named counterparty in an executed agreement or approval record
- amendment delta amount and new total where explicitly stated
- audit or recovery-plan findings stated in official reports

Keep as `Claim` first:

- inferred bidder participation where only one winner is public
- implied deliverables not actually listed
- assumed payment completion based only on authorization
- assumed vendor performance from anecdotal complaints

## Phase 5: Review For Model Stress

At the end of the first three samples, answer:

- was `Procurement` distinct enough from `Decision` to justify a first-class node?
- did `Agreement` stay meaningfully separate from the contract `Record`?
- did `Amendment` need its own node, or was a decision-only view enough?
- were `Deliverable` and `PerformanceReview` common enough to keep first-class?
- did budget and audit surfaces materially improve contract and grant understanding?

## Stop Conditions

Pause and revise the model if:

- the public record rarely distinguishes solicitation from award
- agreements are almost never visible beyond a one-line meeting action
- grant funding is only visible in narrative pages with no durable records
- amendment history cannot be joined reliably to the base agreement
- performance evidence is too thin to justify first-class review nodes
