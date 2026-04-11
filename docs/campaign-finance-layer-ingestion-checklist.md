# Campaign Finance Layer Ingestion Checklist

Date drafted: April 11, 2026

This checklist turns the campaign-finance and disclosure planning docs into an execution sequence.

## Goal

Produce one small but real campaign/disclosure sample basket that pressure-tests:

- `Election`
- `Committee`
- `Candidacy`
- `Filing`
- `EconomicInterestDisclosure`
- `MoneyFlow`
- `Record` with campaign and disclosure form types

## Phase 1: Capture Discovery Surfaces

Capture and manifest these official pages first:

- Marin County `Campaign Finance Reporting And Information`
- Marin County `Campaign Finance Portal`
- Marin County `Statement Of Economic Interests (Form 700)`
- San Rafael `Disclosures`
- FPPC `Statement Of Economic Interests For Candidates`
- FPPC `Contribution Limits: City And County Candidates`
- FPPC `Reporting Behested Payments`
- FPPC `Form 803 Search`
- FPPC `Where To File Form 460`

Minimum output:

- raw HTML or PDF captures
- manifests
- source-registry entries confirmed against live behavior

## Phase 2: Pick Three Sample Threads

### Slot A: Candidate-controlled committee

Select one thread where the public record shows:

- candidate or officeholder
- seat or election context
- committee identity
- at least one campaign filing

Minimum usable outcome:

- one `Election`
- one `Candidacy`
- one `Committee`
- one or more `Filing` objects
- one or more related `MoneyFlow` objects
- supporting `Record` nodes

### Slot B: Outside-money or late-money thread

Select one thread where the public record shows:

- independent expenditure, late contribution, or other outside-money signal
- named committee or spender
- target candidate, seat, or election context

Minimum usable outcome:

- one `Committee`
- one `Filing`
- one or more `MoneyFlow` objects
- one beneficiary actor or election join
- supporting `Record` nodes

### Slot C: Disclosure thread

Select one thread where the public record shows:

- one Form 700 or Form 803 surface
- one identifiable filer or officeholder
- one seat, institution, or office context

Minimum usable outcome:

- one `EconomicInterestDisclosure` or disclosure-linked `Filing`
- one `Actor`
- one `Seat` or `Institution` join
- supporting `Record` nodes

## Phase 3: Normalize Objects

For each selected thread, produce:

- `election-*.json`
- `committee-*.json`
- `candidacy-*.json`
- `filing-*.json`
- `disclosure-*.json`
- `moneyflow-*.json`
- `record-*.json`

Required joins:

- `candidacy.candidate_actor_id`
- `candidacy.seat_id`
- `candidacy.election_id`
- `candidacy.committee_id?`
- `committee.controlling_actor_id?`
- `committee.treasurer_actor_id?`
- `committee.primary_election_id?`
- `filing.committee_id?`
- `filing.filer_actor_id?`
- `filing.filing_institution_id?`
- `filing.election_id?`
- `economic_interest_disclosure.filer_actor_id`
- `economic_interest_disclosure.filing_institution_id`
- `economic_interest_disclosure.seat_id?`
- `money_flow.from_actor_id?`
- `money_flow.to_actor_id?`
- `money_flow.from_committee_id?`
- `money_flow.to_committee_id?`
- `money_flow.beneficiary_actor_id?`
- `money_flow.filing_id?`
- `money_flow.election_id?`

## Phase 4: Evidence Checks

Do not promote a campaign or disclosure fact unless the record supports it clearly.

Safe early promotions:

- committee name and FPPC ID
- filing type and filing date
- stated contribution or expenditure amount
- stated donor, payee, or recipient committee
- candidate-to-seat relationship when the filing or official page states it clearly
- disclosure filer, statement type, and filing officer
- behested-payment amount and recipient when the official disclosure states them
- local-versus-state Form 803 filing boundary when the official guidance states it clearly

Keep as `Claim` first:

- issue alignment inferred only from donor history
- family or employer identity inferred from name similarity
- “influence” conclusions drawn only from contribution adjacency
- officeholder conflict conclusions that are not explicit in the disclosure surface
- the existence of a local filed Form 803 report when only guidance or policy text has been captured

## Phase 5: Review For Model Stress

At the end of the first three samples, answer:

- was `Committee` distinct enough from `Actor` to justify a first-class node?
- did `Election` and `Candidacy` materially improve joins to seats and officeholders?
- did `Filing` stay meaningfully separate from the filing PDF `Record`?
- was `EconomicInterestDisclosure` common enough to keep first-class, or should it collapse into `Filing`?
- did campaign/disclosure records produce useful joins back into meetings, procurement, permits, or appointments?

## Stop Conditions

Pause and revise the model if:

- local filings are too inconsistent to separate committee, filing, and moneyflow cleanly
- official local surfaces do not expose enough structure to anchor election or seat joins
- disclosure pages are mostly dead-end PDFs with no durable filer context
- campaign and disclosure threads cannot be joined back into other civic domains without excessive guesswork
