# Procurement Sample Basket Selection

Verified: April 11, 2026

This document selects the first concrete procurement-layer sample basket.

The goal is not to find the three most important contracts in Marin.

The goal is to pick three official threads that collectively pressure-test:

- `Procurement`
- `Agreement`
- `Amendment`
- `Program`
- `MoneyFlow`
- `PerformanceReview`

## Selection Criteria

The first basket should favor threads that have:

- clear official source surfaces
- enough public record to produce real joins
- different structural patterns rather than three versions of the same thing

## Selected Threads

### Slot A: County solicitation to award

#### Selected thread

- `Board Chambers Audio Visual Refresh / Prime Electric`

#### Why this thread

- It gives a clean county-side `Procurement -> Decision -> Agreement` chain.
- The solicitation is visible as an official RFP.
- The later award is explicitly described in an official county news release tied to a Board approval.
- It is a useful non-NGO, non-social-services control case for the procurement model.

#### Official anchors

- RFP 2883 PDF:
  - https://www.marincounty.gov/sites/g/files/fdkgoe241/files/2025-04/FINAL%20RFP%20-%20BOS%20Chambers%20Audio%20Visual%20Projects.pdf
- County news release on the later approval:
  - https://www.marincounty.gov/news-releases/supervisors-relocating-regular-meetings-accommodate-chamber-upgrades

#### First objects to expect

- one `Procurement`
- one `Decision`
- one `Agreement`
- one vendor `Actor`
- one or more `Record` nodes for the RFP and award materials

#### Immediate open questions

- We still need the exact Board meeting page and packet that memorialized the Prime Electric approval.
- The county news release is enough to select the thread, but not enough to promote the full agreement object without the approval record.

### Slot B: City agreement with amendment or renewal

#### Selected thread

- `Downtown Library Renovation Project`

#### Why this thread

- It has an official project page plus an official procurement posting.
- It has at least one visible procurement-stage page, multiple amendment-stage City Council records, and downstream completion reporting.
- It exercises both professional-services and construction-contract amendment patterns.
- It also bridges city capital spending with outside grant support, which makes it richer than a generic consultant amendment.

#### Official anchors

- Project page:
  - https://www.cityofsanrafael.org/downtown-library-renovation/
- Procurement posting:
  - https://www.cityofsanrafael.org/request-for-proposals-downtown-library-renovation-project/
- First amendment page:
  - https://www.cityofsanrafael.org/meetings/city-council-september-18-2023/
- Second amendment page:
  - https://www.cityofsanrafael.org/meetings/city-council-april-7-2025-special-regular/
- Completion / funding context:
  - https://www.cityofsanrafael.org/reopening-downtown-library-after-renovations/

#### First objects to expect

- one `Project`
- one city-side `Procurement`
- one or more `Agreement` nodes
- one or more `Amendment` nodes
- related `MoneyFlow` objects
- `Record` nodes for the procurement page, meeting pages, and project update pages

#### Immediate open questions

- The first live pass should decide whether the architect agreement and construction contract become separate `Agreement` threads or one grouped project contract family.
- The reopening page says the project was made possible by California State Library funding; we should not model that grant relationship beyond a `Claim` until the underlying award record is captured.

### Slot C: program-funded thread with reporting surface

#### Selected thread

- `Marin County State and Local Fiscal Recovery Funds (SLFRF)`

#### Why this thread

- It is the cleanest current official program-level funding surface with actual public reporting.
- It pressures `Program`, `MoneyFlow`, and `PerformanceReview` even if it does not begin as a single contract thread.
- It gives the procurement tranche one intentionally broader public-spending case instead of only agreement-centric cases.
- It is a strong bridge between Board funding decisions and later public performance reporting.

#### Official anchors

- Program page:
  - https://www.marincounty.gov/departments/executive/budget-and-priority-setting/how-were-using-state-and-local-fiscal-recovery-funds
- Recovery Plan 2025 report page:
  - https://www.marincounty.gov/departments/executive/budget-and-priority-setting/how-were-using-state-and-local-fiscal-recovery-funds/recovery-plan-2025-report
- Recovery Plan 2025 report PDF:
  - https://assets.marincounty.gov/marincounty-prod/public/2025-07/County%20of%20Marin%20ARPA%20Funds%20report%20-%20Jul%2031%202025.pdf
- County single audit reports index:
  - https://www.marincounty.gov/departments/finance/internal-audit/single-audit-reports

#### First objects to expect

- one `Program`
- one or more `MoneyFlow` objects
- one `PerformanceReview`
- supporting `Record` nodes for recovery-plan and audit materials

#### Immediate open questions

- This thread is intentionally broader than a single agreement. The first pass should decide whether SLFRF stays one `Program` node with child funding slices, or whether specific spending areas become child programs.
- We should not infer specific downstream contracts from the recovery page alone.

## Why These Three Together

This basket gives three different patterns:

- county procurement with a visible solicitation and later award
- city capital-project contract family with amendments
- county program-level funding with public reporting

That is a better stress test than three conventional meeting-item contracts.

## Recommended Next Execution Step

Capture the first discovery pages for these three threads:

- county RFP 2883 and county chamber-upgrade approval page
- city Downtown Library Renovation project page and the two City Council amendment pages
- county SLFRF program page and Recovery Plan 2025 report page

Then normalize:

- one `Procurement` candidate for slot A
- one `Project` + `Agreement` family for slot B
- one `Program` + `PerformanceReview` spine for slot C
