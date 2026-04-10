# Criminal Sample Basket Source Bundle

Date drafted: April 10, 2026

This document turns the criminal-justice planning work into a concrete first sample basket.

The goal is to pressure-test the criminal submodel against public Marin source surfaces without overcommitting to a broad criminal-docket ingestion plan.

## Basket Goal

Prove that the graph can connect:

- booking and custody
- charges
- case metadata
- hearings and proceedings
- judge assignment
- attorney roles where visible
- disposition and sentence outcomes where publicly available

The first pass should focus on source surfaces and sample shapes, not on scraping a huge population of criminal cases.

## Public Source Surfaces

The first bundle should rely on these official source surfaces:

- `marin-superior-court-eportal`
  - https://www.marin.courts.ca.gov/online-services/ecourt-online-portal
- `marin-superior-court-court-records-exhibits`
  - https://www.marin.courts.ca.gov/divisions/court-records-exhibits
- `marin-superior-court-judicial-assignments`
  - https://www.marin.courts.ca.gov/general-information/judicial-assignments
- `marin-superior-court-judicial-biographies`
  - https://www.marin.courts.ca.gov/general-information/judicial-biographies
- `marin-sheriff-detention-bureau`
  - https://marinsheriff.gov/about-us/detention-bureau
- `marin-sheriff-warrants`
  - https://marinsheriff.gov/services/warrants
- `marin-sheriff-records`
  - https://marinsheriff.gov/services/records
- `marin-county-da-newsroom`
  - https://marincountyda.org/

## Sample Slots

The first basket should not start as "all cases."

It should start as three narrow sample slots.

## Slot A: Booking-First Open Case

### Why It Is In The Basket

- tests the sheriff -> court join
- proves `CustodyEvent`, booking-stage `Charge`, `Case`, and upcoming `Proceeding`
- gives the cleanest first view of custody and next-hearing data

### Discovery Path

1. detention / booking-log surface
2. case or calendar lookup through `ePortal`
3. judicial assignment lookup for the department

### Minimum Fields To Prove

- defendant identity as an `Actor`
- booking number or booking timestamp
- booking-stage charges
- bail amount or release status where public
- next court appearance
- assigned department and likely judge

### Core Objects To Test

- `Actor`
- `CustodyEvent`
- `Charge` with `charge_stage = booking`
- `Case`
- `Proceeding`
- `Record` with `booking_log_entry` and `calendar_entry`

### Known Risk

- the sheriff surface may show more immediate custody detail than the court surface
- the court surface may lag or may require a separate case-number discovery step

## Slot B: Filed Case With Public Hearings And Disposition

### Why It Is In The Basket

- tests whether a case can be followed beyond booking
- proves `Charge` stage transitions, `Proceeding`, `Disposition`, and `Sentence`
- gives the first serious judge-accountability shape without turning it into a scoreboard

### Discovery Path

1. `ePortal` case search or calendar search
2. court records / records-request page for what is available beyond public index access
3. judicial assignments and biographies for judge normalization
4. optional DA newsroom item if it publicly identifies a charging or conviction event

### Minimum Fields To Prove

- case number
- filed charges
- one or more hearings
- presiding judge
- defense and prosecution role labels if visible
- disposition type
- sentence or supervision outcome where public

### Core Objects To Test

- `Case`
- `Proceeding`
- `Charge` with `charge_stage = filed`
- `AttorneyRepresentation`
- `Disposition`
- `Sentence`
- `Record` with `case_index_record`, `calendar_entry`, and optional `judgment`

### Known Risk

- public remote access may stop at document titles and hearing metadata
- full minute orders or sentencing documents may need a records request

## Slot C: Warrant-Linked Or Post-Booking Control Thread

### Why It Is In The Basket

- tests a second public-safety surface outside simple booking
- helps model cases where the public sees enforcement status before understanding the underlying case
- creates room for later probation, remand, or failure-to-appear analysis

### Discovery Path

1. sheriff warrant surface
2. `ePortal` case or calendar search
3. judicial assignment and proceeding normalization

### Minimum Fields To Prove

- warrant existence or status
- linked case if discoverable
- next proceeding if public
- judge or department

### Core Objects To Test

- `Record` with `warrant_entry`
- `Case`
- `Proceeding`
- optional `ReleaseDecision` or `CustodyEvent`

### Known Risk

- warrant surfaces may be thin and may not expose enough detail to resolve the full case chain cleanly

## Selection Rules

The first sample basket should follow these rules:

- use adult public cases only
- exclude juvenile, sealed, and otherwise confidential matters
- prefer one misdemeanor and one felony if both can be supported by public surfaces
- prefer cases with at least two source surfaces, not one
- prefer cases where the next step in the chain is visible before trying to collect complete history
- avoid putting real person names in planning docs until the sample is actually captured

## Minimum Deliverable

The first criminal sample basket is successful if it proves:

1. one booking-first chain
2. one filed-and-disposed chain
3. one warrant-linked or comparable control chain

and for each chain, the graph can show:

- the records used
- the joins that held
- the joins that failed or stayed ambiguous

## What This Bundle Should Tell Us

After this basket, we should know:

- whether `ePortal` public access is rich enough to support proceeding-level modeling
- whether court records requests are necessary for meaningful sentence or minute-order coverage
- how often booking-stage and filed-stage charges can be safely joined
- whether attorney roles are visible enough to justify early normalization
- whether judge assignment can be tied directly to proceedings or only to departments

## Recommended Next Step

After registering the criminal source surfaces, create a checklist that says:

- what to capture first
- what graph objects each sample slot must yield
- what evidence gaps are acceptable in v1
