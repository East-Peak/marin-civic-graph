# Permit Layer Source Bundle

Verified: April 10, 2026

This source bundle is the first official planning and permit surface set for Marin Civic Graph.

The goal is not to collect every planning page in Marin.

The goal is to identify the source surfaces that actually emit:

- project threads
- applications
- hearing notices
- staff reports
- determinations
- permits
- appeals

## Marin County

### Planning landing page

- URL: https://www.marincounty.gov/departments/cda/planning
- Why it matters:
  - high-level discovery surface for permit help, projects under review, and hearing bodies
- Expected objects:
  - `institution`
  - `claim`
  - `record:administrative_index`

### Get a Planning Permit

- URL: https://www.marincounty.gov/departments/cda/planning/planning-permits
- Why it matters:
  - canonical entry page for planning permit workflow
  - links out to review process, forms, active applications, and appeals
- Expected objects:
  - `application`
  - `permit`
  - `record:administrative_guide`
  - `claim`

### Planning applications under review

- URL: https://www.marincounty.gov/departments/cda/planning/projects
- Why it matters:
  - public discovery spine for active project threads
  - strongest county surface for creating `Project` plus `Application` candidates before hearings occur
- Expected objects:
  - `project`
  - `application`
  - `place`
  - `record:project_status_page`

### Planning Division forms

- URL: https://www.marincounty.gov/departments/cda/planning/planning-permits/planning-division-forms
- Why it matters:
  - exposes concrete application and appeal form families
  - confirms appeal workflow exists as a first-class administrative action
- Expected objects:
  - `record:planning_application_form`
  - `record:appeal_form`
  - `application`
  - `appeal`

### Planning Commission hearings

- URL: https://www.marincounty.gov/departments/cda/planning/boards-commissions-and-public-hearings/planning-commission-hearings
- Why it matters:
  - public hearing surface for permit decisions and appeals
  - emits agendas, staff reports, minutes, and videos
- Expected objects:
  - `meeting`
  - `agenda_item`
  - `decision`
  - `record:agenda`
  - `record:staff_report`
  - `record:minutes`
  - `record:video`
  - `appeal`

### Deputy Zoning Administrator hearings

- URL: https://www.marincounty.gov/departments/cda/planning/boards-commissions-and-public-hearings/deputy-zoning-administrator-hearings
- Why it matters:
  - direct administrative-hearing surface for project determinations
  - strong pressure-test for `Determination`, `Condition`, and appealed decisions
- Expected objects:
  - `meeting`
  - `project`
  - `determination`
  - `record:agenda`
  - `record:staff_report`
  - `record:minutes`
  - `record:audio`

## San Rafael

### Apply to Planning Online

- URL: https://www.cityofsanrafael.org/apply-to-planning-online/
- Why it matters:
  - official planning portal explainer page
  - links to OpenGov categories and submittal requirements
- Expected objects:
  - `application`
  - `permit`
  - `record:application_guide`
  - `record:submittal_requirements`

### San Rafael OpenGov planning category

- URL: https://cityofsanrafaelca.portal.opengov.com/categories/1083
- Discovery URL: https://www.cityofsanrafael.org/opengov
- Why it matters:
  - likely system of record for live application entry and status
  - strongest city-side project and application surface if browser access remains stable
- Expected objects:
  - `project`
  - `application`
  - `permit`
  - `record:portal_status_entry`

### Major Planning Projects 2025

- URL: https://www.cityofsanrafael.org/major-planning-projects-2025/
- Why it matters:
  - curated city-side project registry
  - useful for project identity normalization even before deep extraction
- Expected objects:
  - `project`
  - `place`
  - `issue`
  - `claim`

### Planning Commission meetings

- URL: https://www.cityofsanrafael.org/planning-commission-meetings/
- Why it matters:
  - public hearing archive for project approvals, denials, and study sessions
- Expected objects:
  - `meeting`
  - `agenda_item`
  - `decision`
  - `record:agenda`
  - `record:packet`
  - `record:minutes`
  - `record:video`

### Zoning Administrator hearings

- URL: https://www.cityofsanrafael.org/zoning-administrator-hearings/
- Why it matters:
  - city administrative-hearing archive with agendas, packets, minutes, and videos
  - likely strongest city surface for staff-level or administrator-level project determinations
- Expected objects:
  - `meeting`
  - `project`
  - `determination`
  - `record:agenda`
  - `record:packet`
  - `record:minutes`
  - `record:video`

## Recommended First Sample Basket

Use three sample slots:

### Slot A: San Rafael active or recent major planning project

Goal:

- pressure-test `Project` identity
- connect project page to hearing surfaces and application portal

### Slot B: Marin County application under review

Goal:

- pressure-test `Project` plus `Application` before final outcome
- test place-based discovery joins

### Slot C: appealed or denied permit thread

Goal:

- pressure-test `Determination`, `Appeal`, and appeal-decision joins

## Notes

- Marin County official pages are browser-visible through the web tool but can return Cloudflare blocks to ordinary CLI fetches.
- San Rafael's OpenGov surfaces appear live, but they may require browser capture rather than simple static fetches.
- This bundle is about planning and land-use style administrative process, not full building-permit ingestion.
