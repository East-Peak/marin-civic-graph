# Permit Sample Basket Selection

Verified: April 10, 2026

This document picks the first three concrete permit-thread samples for Marin Civic Graph.

The goal is to stop speaking about the permit layer abstractly and pressure-test it against real official project pages and hearing surfaces.

## Primary Basket

### Slot A: 700 Irwin St. (San Rafael)

- Project page: https://www.cityofsanrafael.org/700-irwin-st
- Major projects index: https://www.cityofsanrafael.org/major-planning-projects-2025/
- Hearing notice: https://www.cityofsanrafael.org/public-hearing-for-project-at-700-irwin/

Why this is in:

- strong city-side `Project` page with applicant, APN, zoning, project planner, status, timeline, and project documents
- explicit statement that the project was submitted on April 10, 2025 and is currently `Application is Complete`
- likely cleanest city example for joining a major-project page to planning-hearing and permitting surfaces

What it pressure-tests:

- `Project` identity on the city side
- project-to-place joins
- applicant and planner joins
- active application status without final action yet
- city `Project` page to hearing notice to permit-record joins

Why it beats the alternatives:

- `Northgate Town Square` is important, but it is already in a later-stage approved posture and has a much larger archived entitlement history
- `700 Irwin St.` is narrower and cleaner for a first city project thread

### Slot B: Metropolis San Pedro Road, LP Tentative Map (P5139) (Marin County)

- Project page: https://www.marincounty.gov/departments/cda/planning/projects/san-rafael-santa-venetia/metropolis-san-pedro-rd-lp-p5139
- County applications index: https://www.marincounty.gov/departments/cda/planning/projects

Why this is in:

- county project page exposes project number `P5139`, status `Under Review`, applicant, APNs, location, and project materials
- one thread already spans multiple requested approvals: Vesting Tentative Map plus Tree Removal Permit
- the page is a good county-side example of one `Project` with multiple permit types inside one active application thread

What it pressure-tests:

- county `Project` identity
- `Application` versus `Permit` distinction
- one project touching multiple permit/determination objects
- APN and place joins in unincorporated Marin
- county project page to future hearing-surface joins

Why it beats the alternatives:

- `Pierce Co Properties (Cal Park Glen) Housing Compliance Review (P6168)` is also good, but `P5139` is structurally richer because it already combines subdivision and tree-removal components in one thread

### Slot C: Souang Vesting Tentative Map and Housing Compliance Review (P4134) (Marin County)

- Project page: https://www.marincounty.gov/departments/cda/planning/projects/san-rafael-lucas-valley-marinwood/souang-vesting-tentative-map-and-housing-compliance-review-p4134
- Planning Commission hearing page: https://www.marincounty.gov/node/25691
- Related CEQA / hearing surface: https://www.marincounty.gov/departments/cda/planning/environmental-planning/current-ceqa-projects/souang-vesting-tentative-map-and-tree-removal-permit

Why this is in:

- explicit appeal chain is already visible in the official record
- project page includes original project materials, a final ministerial decision from May 14, 2025, and later public-hearing materials
- official pages show a Planning Commission hearing on December 8, 2025 for the `Reilly appeal`
- the same project page also shows a Board of Supervisors hearing on March 10, 2026

What it pressure-tests:

- `Project` surviving across original application, decision, appeal, and later hearing stages
- `Determination` versus `Decision`
- `Appeal` as a first-class object
- one project linked to multiple hearings and multiple official packets
- appeal-material records, supplemental memoranda, and resolution attachments

Why it is the right appeal thread:

- this is the cleanest official county example I found where the project page itself already exposes the appeal sequence, not just a bare hearing listing

## Reserve Threads

Use these if the primary basket needs a simpler or broader control sample.

### Reserve A: Catholic Charities CYO Archdiocese of San Francisco Tree Removal Permit (P5993)

- https://www.marincounty.gov/departments/cda/planning/projects/san-rafael-unincorporated/catholic-charities-cyo-archdiocese-sf-trp-p5993

Why keep it in reserve:

- simple approved county permit thread
- contains a completeness letter and a final decision document
- good control case for `Determination` plus `Permit` without a big hearing or appeal stack

### Reserve B: Pierce Co Properties (Cal Park Glen) Housing Compliance Review (P6168)

- https://www.marincounty.gov/departments/cda/planning/projects/san-rafael-unincorporated/pierce-co-prop-cal-park-glen-hcr-p6168

Why keep it in reserve:

- active county housing thread with status `Under Review`
- useful if `P5139` turns out to be too map-heavy or too subdivision-specific

### Reserve C: Northgate Town Square (San Rafael)

- https://www.cityofsanrafael.org/northgatetownsquaredev/

Why keep it in reserve:

- approved on December 2, 2024 according to the official city project page
- likely strong for a later crossover between `Project`, `Decision`, and long-running entitlement history
- too big for the first permit-only pressure test, but high-value later

## Why This Basket Is Balanced

Together these three slots cover:

- city-side project pages
- county-side project pages
- active under-review applications
- multi-permit requests
- an explicit appeal chain
- hearing pages and hearing packets
- project pages with attached materials and status labels

That is enough to test whether the permit layer really needs:

- `Project`
- `Application`
- `Permit`
- `Determination`
- `Condition`
- `Appeal`

## Immediate Next Moves

1. Capture raw discovery pages for these three threads.
2. Normalize one `Project` object per thread.
3. Extract visible application numbers, applicants, statuses, APNs, and hearing dates.
4. Split the Souang thread into original decision records versus appeal records.
5. Decide whether `Condition` should be promoted in slot B or held for the reserve approved-permit control case.

## Source Basis

The selection is based on official public pages reviewed on April 10, 2026:

- San Rafael Major Planning Projects page lists `700 Irwin St.` and other current projects
- the `700 Irwin St.` project page states the project was submitted on April 10, 2025 and that the application is complete
- Marin County project pages for `P5139`, `P6168`, and `P5993` expose project status, applicant, parcel, and materials
- the Souang `P4134` project page exposes both the original decision materials and the later appeal-hearing materials
- the official county Planning Commission hearing page for December 8, 2025 explicitly labels the Souang matter as the `Reilly Appeal`
