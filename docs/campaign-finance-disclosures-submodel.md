# Campaign Finance And Disclosure Submodel

Verified: April 11, 2026

This document defines the campaign-finance and disclosure extension for Marin Civic Graph.

The goal is to make committees, filings, disclosures, and campaign-adjacent money legible without pretending the project is a full statewide campaign-finance warehouse.

## Scope

The first version should model:

- local candidate and officeholder committees
- general-purpose and independent-expenditure committees when they touch Marin races or officeholders
- candidate-to-seat and candidate-to-election relationships
- filed campaign reports such as Form 460, Form 496, and Form 497
- Statement of Economic Interests filings such as Form 700
- behested-payment reporting such as Form 803
- campaign and disclosure money flows that can be joined back to meetings, contracts, permits, and recurring actors

It should not assume first-pass access to:

- complete statewide committee histories
- full lobbying datasets
- household-level donor identity cleanup beyond what the filings support
- automatic political influence scores
- perfect issue attribution for every donor or expenditure

## Public Record Surfaces

The current planning assumption for Marin is:

- Marin County Elections exposes local campaign-finance guidance and the public NetFile portal for local filings
- Marin County Elections also exposes Statement of Economic Interests guidance for county filers
- San Rafael exposes Form 700, Form 803, and related disclosure records on the public disclosures page
- FPPC surfaces the filing rules, contribution-limit context, and disclosure guidance needed to normalize the local records correctly

After the first Form 803 slice, the more precise reading is:

- San Rafael's public disclosure spine is still useful, but the currently visible public page content is primarily a Form 700 / Form 804 / Form 806 surface
- the public San Rafael SEI NetFile portal is currently a Form 700-oriented search surface, not a visible Form 803 search surface
- the FPPC Form 803 search page is a state-official search surface, not a local-official filing index
- for local officials, the governing Form 803 rule is still local-agency filing first

That means the graph should begin with:

- committee and filing portals
- official disclosure pages
- FPPC guidance pages that define filing meaning and timing

not with the assumption that every interesting contribution or conflict surface is already in one clean API.

This distinction matters for Form 803 work:

- local `Form 803` discovery should begin with the local agency and Clerk-facing records
- FPPC `Form 803` search should be treated as a state-level reference surface and a schema guide, not as the default local filing source

## Core Graph Objects

### Election

A bounded contest context for a seat, office, or measure.

Examples:

- 2026 San Rafael City Council District 2 election
- 2026 Marin County Supervisor District 3 election

Key fields:

- `id`
- `jurisdiction_place_id`
- `election_type`
- `election_date`
- `cycle_label?`
- `seat_id?`
- `status`

### Committee

A regulated campaign-finance entity with its own filing identity.

Examples:

- candidate-controlled committee
- officeholder committee
- general-purpose committee
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

Important distinction:

- the candidate or donor is an `Actor`
- the regulated filing entity is a `Committee`
- a filing PDF is still a `Record`

### Candidacy

A person running for, holding, or qualifying for a specific seat in a specific election cycle.

Examples:

- one candidate for one city-council seat
- one appointed incumbent later seeking election to the same seat

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

A structured filing object tied to a committee, candidate, or disclosure process.

Examples:

- Form 460 semiannual statement
- Form 496 independent-expenditure report
- Form 497 late-contribution report
- Form 501 candidate intention statement

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

A structured Statement of Economic Interests object backed by a Form 700 or similar official disclosure.

Examples:

- annual Form 700
- assuming-office statement
- leaving-office statement
- candidate statement

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

## Existing Objects Reused Heavily

### Actor

Reuse `Actor` for:

- donors
- candidates
- officeholders
- treasurers
- vendors paid by campaign committees
- nonprofits or businesses receiving behested payments

### Seat

Reuse `Seat` for:

- the office a candidacy or officeholder relationship is tied to
- later joins back into decisions, appointments, and public disclosures

### MoneyFlow

Keep `MoneyFlow` as the normalized money object for:

- contributions
- campaign expenditures
- independent expenditures
- behested payments

The campaign layer adds better filing, committee, and election context for those flows.

### Record

Use existing `Record` nodes with these priority types:

- `financial_record`
  - `form_460`
  - `form_496`
  - `form_497`
  - `form_501`
  - `form_700`
  - `form_803`
  - `netfile_export`
- `administrative_record`
  - `candidate_information_page`
  - `filing_guide`
- `meeting_record`
  - disclosure or appointment items that tie an official back to a filing or recusal context

## Relationship Pattern

The default chain should be:

```text
Seat -> contested_in -> Election
Actor -> runs_as -> Candidacy
Candidacy -> for_seat -> Seat
Candidacy -> in_election -> Election
Committee -> supports_or_controls -> Candidacy
Committee -> controlled_by -> Actor
Committee -> treasurer_is -> Actor
Committee -> files -> Filing
Filing -> reports -> MoneyFlow
Actor -> files -> EconomicInterestDisclosure
EconomicInterestDisclosure -> tied_to -> Seat / Institution
MoneyFlow -> joins_to -> Committee / Actor / Election / Issue
Record -> evidences -> Committee / Filing / Disclosure / MoneyFlow
```

## Recommended First Deliverables

Start with three small threads:

1. one candidate-controlled committee with a clean Form 460 history
2. one late-contribution or independent-expenditure thread that shows outside money
3. one Form 700 or Form 803 disclosure thread for a local officeholder

## Notes

- the campaign layer should stay evidence-first; donor recurrence and issue alignment are derived views, not primitive facts
- one person can appear in several roles across this layer: candidate, officeholder, filer, treasurer, donor, behested-payment requester
- many of the most useful joins are cross-domain:
  - donor also appears in `PublicComment`
  - officeholder files Form 700 and later votes on a contract
  - behested-payment requester is tied to a `Seat` and `Institution`
