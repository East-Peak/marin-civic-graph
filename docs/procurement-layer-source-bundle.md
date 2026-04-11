# Procurement Layer Source Bundle

Verified: April 10, 2026

This source bundle is the first official procurement, grant, contract, and performance surface set for Marin Civic Graph.

The goal is not to mirror every public purchasing system.

The goal is to identify the official surfaces that actually emit:

- solicitations
- procurement guidance
- contract and grant approvals
- amendments
- budget and recovery-plan context
- audit and performance signals

## Marin County

### Contracting Opportunities

- URL: https://www.marincounty.gov/contracting-opportunities
- Why it matters:
  - public county-wide solicitation surface
  - exposes active RFP / RFQ / IFB style opportunities
- Expected objects:
  - `procurement`
  - `record:solicitation`
  - `record:addendum`
  - `actor`

### Procurement Division

- URL: https://publicworks.marincounty.gov/agencies/procurement/
- Why it matters:
  - canonical procurement-policy and process surface
  - links to vendor requirements and contracting systems
- Expected objects:
  - `institution`
  - `procurement`
  - `record:procurement_manual`
  - `record:procurement_form`
  - `claim`

### Board of Supervisors Meetings

- URL: https://www.marincounty.gov/departments/board/board-supervisors-meetings
- Why it matters:
  - main approval surface for larger contracts, grant acceptances, amendments, and appropriations
  - where procurement and grant decisions usually become explicit
- Expected objects:
  - `meeting`
  - `agenda_item`
  - `decision`
  - `agreement`
  - `amendment`
  - `money_flow`
  - `record:agenda`
  - `record:packet`
  - `record:minutes`

### Budget and Priority Setting

- URL: https://www.marincounty.gov/departments/executive/budget-and-priority-setting
- Why it matters:
  - central county surface for budget reports, service metrics, recovery funding, and delegated-agreement discovery
  - bridges procurement into appropriations and grant-funded programs
- Expected objects:
  - `program`
  - `money_flow`
  - `record:budget_report`
  - `record:financial_statement`
  - `claim`

### How We Measure Success

- URL: https://www.marincounty.gov/departments/executive/budget-and-priority-setting/how-we-measure-success
- Why it matters:
  - official performance surface tied to public service metrics
  - useful for `PerformanceReview` and program outcome context
- Expected objects:
  - `program`
  - `performance_review`
  - `record:performance_report`
  - `claim`

### State and Local Fiscal Recovery Funds

- URL: https://www.marincounty.gov/departments/executive/budget-and-priority-setting/how-were-using-state-and-local-fiscal-recovery-funds
- Why it matters:
  - direct grant-allocation and reporting surface
  - exposes recovery-plan reports and spending categories
- Expected objects:
  - `program`
  - `money_flow`
  - `decision`
  - `performance_review`
  - `record:recovery_plan`

### FY 2024 ACFR

- URL: https://assets.marincounty.gov/marincounty-prod/public/2025-03/acfr-fiscal-year-2024.pdf
- Why it matters:
  - county-wide financial-statement surface
  - strong context for grants, liabilities, spending categories, and audit posture
- Expected objects:
  - `record:financial_statement`
  - `claim`
  - `money_flow`

## San Rafael

### Bids and Proposals

- URL: https://www.cityofsanrafael.org/bids-and-proposals/
- Why it matters:
  - strongest current city-wide solicitation surface
  - includes public works bids and professional-services RFP / RFQ postings
- Expected objects:
  - `procurement`
  - `record:solicitation`
  - `record:addendum`
  - `actor`

### City Council Meetings

- URL: https://www.cityofsanrafael.org/city-council-meetings/
- Why it matters:
  - main city approval surface for agreements, amendments, and grant acceptance
  - also exposes staff reports and correspondence that describe scope, budget, and operator choice
- Expected objects:
  - `meeting`
  - `agenda_item`
  - `decision`
  - `agreement`
  - `amendment`
  - `money_flow`
  - `record:agenda`
  - `record:packet`
  - `record:minutes`

### San Rafael ACFR 2023

- URL: https://www.cityofsanrafael.org/documents/san-rafael-acfr-2023/
- Why it matters:
  - city-level financial statement
  - useful for grant, capital, and major-fund context
- Expected objects:
  - `record:financial_statement`
  - `claim`
  - `money_flow`

### San Rafael 2023 Single Audit

- URL: https://www.cityofsanrafael.org/documents/2023-single-audit/
- Why it matters:
  - official compliance and federal-awards review surface
  - strong early source for `PerformanceReview`
- Expected objects:
  - `performance_review`
  - `record:single_audit`
  - `claim`

## Tactical Example Surfaces

These are not the only sources, but they are strong pressure-test examples for the layer.

### San Rafael RFI: Organizational Development Services

- URL: https://www.cityofsanrafael.org/request-for-information-for-organizational-development-services/
- Why it matters:
  - city-side consultant-selection example
  - useful for on-call professional-services modeling

### San Rafael RFQ: Planning and CEQA Services

- URL: https://www.cityofsanrafael.org/rfq-planning-and-ceqa-services/
- Why it matters:
  - city-side on-call consultant procurement example
  - likely to create repeat vendor recurrence and amendment history

### Measure P: Albert Park Library and Community Center

- URL: https://www.cityofsanrafael.org/measure-p-albert-park-library-community-center/
- Why it matters:
  - capital program page that links project funding, agreements, and updates
  - good bridge between `Program`, `Project`, `Decision`, and `Agreement`

## Recommended First Sample Basket

Use three sample slots:

### Slot A: County solicitation to award

Goal:

- pressure-test `Procurement -> Decision -> Agreement`

Good source family:

- `Contracting Opportunities`
- county procurement division page
- Board of Supervisors meeting packet

### Slot B: City award with later amendment or renewal

Goal:

- pressure-test `Agreement -> Amendment`

Good source family:

- `Bids and Proposals`
- City Council meetings
- project or program update page if it exists

### Slot C: Grant-funded program with reporting or audit surface

Goal:

- pressure-test `Program`, `MoneyFlow`, and `PerformanceReview`

Good source family:

- county `State and Local Fiscal Recovery Funds`
- county `How We Measure Success`
- city `Single Audit`
- city capital-program page such as `Measure P`

## Notes

- county procurement and finance surfaces are split across multiple official sites and PDFs; that is normal for this layer
- city solicitations are public, but the most important contract details often still live in council staff reports
- audit, recovery-plan, and financial-report surfaces are often the only public way to tie agreements back to funding and outcomes
