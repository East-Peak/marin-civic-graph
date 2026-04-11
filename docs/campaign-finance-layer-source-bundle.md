# Campaign Finance Layer Source Bundle

Verified: April 11, 2026

This source bundle is the first official campaign-finance and disclosure surface set for Marin Civic Graph.

The goal is not to mirror the entire FPPC ecosystem.

The goal is to identify the official surfaces that actually emit:

- committee and candidate filing context
- campaign reports
- local disclosure pages
- Statement of Economic Interests material
- behested-payment reporting
- filing and contribution-limit guidance needed to interpret the records correctly

## Marin County

### Campaign Finance Reporting And Information

- URL: https://www.marincounty.gov/departments/elections/current-election/candidate-guide/campaign-finance-reporting-and-information
- Why it matters:
  - official county filing guide for local committees and candidates
  - ties Marin filing practice to NetFile and FPPC forms
- Expected objects:
  - `committee`
  - `filing`
  - `record:filing_guide`
  - `claim`

### Campaign Finance Portal

- URL: https://netfile.com/agency/cmar/
- Why it matters:
  - strongest public local filing portal for Marin campaign-finance records
  - likely emits committee names, filing periods, and line-item campaign data
- Expected objects:
  - `committee`
  - `filing`
  - `money_flow`
  - `record:netfile_export`

### Statement Of Economic Interests (Form 700)

- URL: https://www.marincounty.gov/departments/elections/campaign-and-candidate-filing-and-information/statement-economic-interests-form-700
- Why it matters:
  - official county disclosure guidance for county officers and candidates
  - bridges elections into conflict and economic-interest disclosures
- Expected objects:
  - `economic_interest_disclosure`
  - `record:form_700`
  - `actor`
  - `seat`

## San Rafael

### Disclosures Page

- URL: https://www.cityofsanrafael.org/disclosures/
- Why it matters:
  - official city disclosure spine
  - exposes Form 700, Form 803, and related ethics/disclosure surfaces
- Expected objects:
  - `economic_interest_disclosure`
  - `filing`
  - `money_flow`
  - `record:form_700`
  - `record:form_803`

## FPPC

### Statement Of Economic Interests For Candidates

- URL: https://www.fppc.ca.gov/learn/campaign-rules/candidate-toolkit/statement-of-economic-interests-for-candidates.html
- Why it matters:
  - canonical state guidance for how candidate Form 700 obligations work
  - helps normalize local filing timing and statement type
- Expected objects:
  - `record:guidance`
  - `claim`

### Contribution Limits: City And County Candidates

- URL: https://www.fppc.ca.gov/learn/campaign-rules/contribution-limits/city-county-contribution-limits.html
- Why it matters:
  - official contribution-limit reference for local candidate analysis
  - useful for interpreting committee behavior without inventing limits
- Expected objects:
  - `record:guidance`
  - `claim`

### Reporting Behested Payments

- URL: https://www.fppc.ca.gov/learn/payments-gifts-and-other-benefits/behested-payments/reporting-behested-payments.html
- Why it matters:
  - canonical state guidance for Form 803
  - defines what the graph should and should not treat as a behested payment
- Expected objects:
  - `record:guidance`
  - `claim`

### Where To File Form 460

- URL: https://www.fppc.ca.gov/learn/campaign-rules/campaign-disclosure-manual/where-to-file-form-460.html
- Why it matters:
  - official FPPC filing guidance for committee statements
  - useful for distinguishing local filing officers and committee types
- Expected objects:
  - `record:guidance`
  - `claim`

## Recommended First Sample Basket

Use three sample slots:

### Slot A: Candidate-controlled committee

Goal:

- pressure-test `Election -> Candidacy -> Committee -> Filing -> MoneyFlow`

Good source family:

- Marin County campaign-finance guide
- Marin NetFile portal
- local candidate or officeholder pages where relevant

### Slot B: Outside-money thread

Goal:

- pressure-test independent expenditure or late-contribution handling

Good source family:

- NetFile portal
- FPPC filing guidance
- local meeting or issue context if the committee later appears elsewhere

### Slot C: Disclosure thread

Goal:

- pressure-test `EconomicInterestDisclosure` and `BehestedPayment` joins back to offices and institutions

Good source family:

- San Rafael disclosures page
- Marin County Form 700 page
- FPPC Form 700 / Form 803 guidance

## Notes

- local filing portals and clerk disclosure pages are likely to be the highest-value operational sources
- FPPC pages are mostly interpretive scaffolding, but they matter because they define filing meaning and timing
- campaign and disclosure threads should be joinable back into meetings, permits, procurement, and appointments rather than living as a separate political silo
