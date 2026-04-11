# Procurement, Grants, Contracts, And Performance Submodel

Verified: April 10, 2026

This document defines the procurement and public-spending extension for Marin Civic Graph.

The goal is to make contract, grant, and vendor relationships legible without pretending we have a perfect ERP mirror.

## Scope

The first version should model:

- solicitations and competitive selection processes
- contract and grant authorizations
- operative agreements
- amendments and renewals
- deliverables and reporting obligations
- performance and compliance review surfaces
- money movement and obligations linked to decisions, programs, and counterparties

It should not assume first-pass access to:

- full invoice-level payment systems
- complete purchase-card detail
- every signed agreement binary
- internal performance dashboards that are not published

## Public Record Surfaces

The current planning assumption for Marin is:

- Marin County exposes active solicitations and procurement guidance on public procurement pages
- Marin County Board of Supervisors packets surface contract and grant approvals above threshold
- Marin County budget, recovery-plan, and service-metric pages expose funding allocation and performance context
- San Rafael exposes bid and proposal postings on the public city site
- San Rafael City Council packets expose contract awards, amendments, and grant acceptances
- audit and financial-report pages expose downstream compliance and spending context

That means the graph should begin with:

- solicitation and approval surfaces
- agreement and amendment records
- audit, recovery-plan, and performance-report surfaces

not with the assumption that every payment or deliverable is directly published in one structured feed.

## Core Graph Objects

### Procurement

A bounded solicitation or vendor-selection process run by a public institution.

Examples:

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

A durable operative relationship between a public institution and a counterparty.

Examples:

- professional services agreement
- public works contract
- grant agreement
- subrecipient agreement
- memorandum of understanding
- on-call consulting agreement

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

Important distinction:

- the signed contract or grant agreement PDF is a `Record`
- the ongoing contractual relationship is an `Agreement`
- the meeting action that authorizes it is a `Decision`

### Amendment

A bounded change to an existing agreement.

Examples:

- amount increase
- scope change
- term extension
- no-cost extension
- amendment and restatement

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

A promised output, milestone, or reporting obligation under an agreement or grant.

Examples:

- annual work plan
- quarterly performance report
- outreach milestone
- environmental review package
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

A record-backed evaluation, compliance, or monitoring object tied to an agreement or funded program.

Examples:

- annual performance report
- single audit finding
- subrecipient compliance review
- recovery-plan progress report
- board update on funded program outcomes

Key fields:

- `id`
- `agreement_id?`
- `program_id?`
- `review_type`
- `period_start?`
- `period_end?`
- `status`
- `summary?`

## Existing Objects Reused Heavily

### Decision

Use `Decision` for:

- contract authorization
- amendment approval
- grant acceptance
- appropriation
- budget adjustment

### MoneyFlow

Keep `MoneyFlow` as the normalized money object for:

- obligation
- appropriation
- grant award
- reimbursement
- payment

The procurement layer adds better upstream context for those flows.

### Program

Reuse `Program` for:

- service program operated under contract
- grant-funded initiative
- capital program with multiple procurements and agreements

Examples:

- sanctioned camping operations contract
- local vendor priority program
- Measure P library and community center capital program
- State and Local Fiscal Recovery Funds spending program

## Supporting Record Types

Use existing `Record` nodes with these priority classes and types:

- `contract_record`
  - `solicitation`
  - `addendum`
  - `bid_tabulation`
  - `agreement`
  - `amendment`
  - `scope_of_work`
- `financial_record`
  - `budget_report`
  - `audit_report`
  - `single_audit`
  - `recovery_plan`
  - `financial_statement`
- `program_record`
  - `performance_report`
  - `compliance_report`
  - `grant_guidance`

## Relationship Pattern

The default chain should be:

```text
Institution -> issues -> Procurement
Procurement -> results_in -> Decision
Decision -> authorizes -> Agreement
Agreement -> funds_or_operates -> Program / Project
Agreement -> amended_by -> Amendment
Agreement -> requires -> Deliverable
Program / Agreement -> reviewed_by -> PerformanceReview
MoneyFlow -> tied_to -> Agreement / Amendment / Decision
Record -> evidences -> any of the above
```

## Recommended First Deliverables

Start with three small threads:

1. one competitive county solicitation that later appears in Board approval materials
2. one city professional-services or public-works award that later receives an amendment
3. one grant-funded program with a recovery-plan, audit, or performance-report surface

This is enough to pressure-test:

- `Procurement`
- `Agreement`
- `Amendment`
- `Deliverable`
- `PerformanceReview`
- the split between `Decision`, `MoneyFlow`, and `Record`

## Methodology Notes

- do not infer that a vendor submitted a proposal unless the public record says so
- do not treat every grant mention as a separate `Program`
- do not collapse a contract PDF, the approval vote, and the ongoing agreement into one node
- keep payments and obligations separate where the records separate them

## Why This Layer Matters

This is one of the cleanest accountability surfaces in the whole project.

It ties together:

- NGO and vendor recurrence
- public money
- board and council approvals
- grant-funded program implementation
- performance and compliance review

That makes it a strong bridge between meetings, records, money, and outcomes.
