# Domain Expansion Matrix

Date drafted: April 10, 2026

This document maps the next major domains the graph could absorb after the initial meetings, records, money, and legal-pressure-test work.

The goal is not to ingest everything.

The goal is to identify:

- which domains materially change the graph
- which new nodes and joins they require
- which public source surfaces are actually available
- which domains should start narrow because the public record is partial or risky

## Expansion Principles

- expand by power surface, not just by document type
- prefer official, structured, repeatedly available records
- keep evidence and evaluation separate
- treat derived accountability views as outputs, not primitive stored facts
- do not assume all domains have the same public-access conditions

## Domain Families

### 1. Permits, Applications, Denials, And Appeals

Why it matters:

- many important local fights never become headline council items
- this is where housing, shelters, street changes, and business restrictions often get decided

Primary institutions:

- city planning departments
- county planning department
- building and fire officials
- zoning administrators
- planning commissions
- hearing officers

Primary record types:

- application
- notice of completeness
- staff report
- hearing notice
- determination letter
- conditions of approval
- denial letter
- appeal filing
- appeal decision

New graph objects:

- `Project`
- `Application`
- `Permit`
- `Determination`
- `Condition`
- `Appeal`

Key joins:

- applicant `Actor`
- parcel or site `Place`
- reviewing `Institution`
- hearing `Meeting` or `Proceeding`
- resulting `Decision`
- related `Case` if litigated

Recommended first deliverable:

- one project thread from application through approval, denial, or appeal

### 2. Land Use, Housing, And Development

Why it matters:

- local power often hides in parcel-level and corridor-level land use decisions
- this is where planning, neighborhood politics, and outside regulators collide

Primary institutions:

- city councils
- county board
- planning commissions
- design review bodies
- county and city planning staff

Primary record types:

- general plan amendments
- zoning text amendments
- use permits
- subdivision maps
- housing element records
- CEQA records
- development agreements

New graph objects:

- `Project`
- `Parcel`
- `LandUseAction`
- `EnvironmentalReview`

Key joins:

- `Project` to `Place`
- `LandUseAction` to `Decision`
- `EnvironmentalReview` to `Record`
- applicant and opponent `Actor` joins

Recommended first deliverable:

- one housing or shelter project with parcel, hearing, appeal, and litigation joins

### 3. Code Enforcement, Nuisance, And Abatement

Why it matters:

- a lot of real power is administrative and coercive, not legislative
- this surface intersects homelessness, business regulation, unsafe properties, and encampment clearance

Primary institutions:

- code enforcement
- public works
- fire marshal
- city attorney or county counsel
- hearing officers

Primary record types:

- notice of violation
- inspection report
- abatement order
- administrative citation
- hearing notice
- compliance report
- settlement agreement

New graph objects:

- `EnforcementAction`
- `Violation`
- `Inspection`
- `AbatementOrder`

Key joins:

- responsible `Actor`
- affected `Place`
- enforcing `Institution`
- resulting `Decision`
- related `Case` or `Program`

Recommended first deliverable:

- one enforcement thread from notice through compliance, appeal, or litigation

### 4. Procurement, Grants, Contracts, And Vendor Performance

Why it matters:

- money is one of the cleanest accountability surfaces
- this is where NGOs, vendors, and public programs become legible

Primary institutions:

- city manager offices
- county executive offices
- departments issuing RFPs
- boards approving contracts

Primary record types:

- request for proposals
- bid tabulations
- staff reports
- contracts
- amendments
- grant agreements
- performance reports
- renewal approvals

New graph objects:

- `Procurement`
- `Agreement`
- `Amendment`
- `Deliverable`
- `PerformanceReview`

Key joins:

- solicitation `Procurement`
- award or approval `Decision`
- operative `Agreement`
- vendor or grantee `Actor`
- approving `Decision`
- operating `Program`
- affected `Issue`
- affected `Place`

Recommended first deliverable:

- one recurring vendor or nonprofit across a solicitation, award, amendment, and performance or audit surface

### 5. Campaign Finance, Disclosures, And Influence

Why it matters:

- this is one of the strongest recurring-actor surfaces
- it ties donors, officials, committees, and outside organizations into one network

Primary institutions:

- Marin elections
- FPPC
- city clerks

Primary record types:

- Form 460
- Form 497
- Form 700
- Form 803
- independent expenditure filings

New graph objects:

- `Committee`
- `Contribution`
- `IndependentExpenditure`
- `EconomicInterestDisclosure`
- `BehestedPayment`

Key joins:

- donor `Actor`
- recipient candidate or committee `Actor`
- office or `Seat`
- related `Issue`
- recurring appearance in `PublicComment`, `Membership`, or `Record`

Recommended first deliverable:

- one issue-aligned donor and organization recurrence map

### 6. Criminal Justice And Court Supervision

Why it matters:

- lower-level courts shape public safety and local disorder outcomes in ways that are not very legible to the public
- judges, prosecutors, public defenders, and repeat defendants all interact through records that are partly public and partly restricted

Important constraint:

- this domain has real public value, but public access is narrower than people often assume
- the graph should start with public case index surfaces and explicit outcomes, not with a hand-wavy “bad judge” score

Public Marin source surfaces currently available:

- Marin Superior Court `ePortal` public access for case and calendar search
- Marin Superior Court records requests and in-person court-record inspection
- Marin Sheriff public booking log
- Marin County online warrant search
- Marin Superior Court judicial assignments
- Marin Superior Court judicial biographies

What those public surfaces appear to provide:

- booking-level arrest and custody data
- booked charges, bail, and next court appearance from sheriff surfaces
- warrant existence
- case metadata, parties, filed-document titles, and past or future hearings from `ePortal`
- judge roster and department assignments

What they do not provide remotely to the general public:

- broad remote access to criminal PDFs and minute records
- a bulk criminal-docket export
- easy statewide person-level matching

Primary institutions:

- Marin Superior Court
- sheriff
- district attorney
- public defender
- probation

Primary record types:

- booking log entry
- warrant entry
- case index record
- docket or register of actions
- hearing calendar entry
- minute order when available through records request
- judgment or sentencing order

New graph objects:

- `Case` with `case_type = criminal_prosecution`
- `Charge`
- `CustodyEvent`
- `ReleaseDecision`
- `Proceeding`
- `Disposition`
- `Sentence`
- `AttorneyRepresentation`

Key joins:

- defendant `Actor` to `Case`
- `Charge` to `Case`
- `CustodyEvent` to defendant `Actor`
- `Proceeding` to `Judge` `Actor`
- `AttorneyRepresentation` to defense and prosecution `Actor`
- `Disposition` and `Sentence` to `Charge`, `Case`, `Judge`, and `Record`

Methodology guardrails:

- model event-level facts first
- keep judge evaluation downstream and derived
- do not infer a judge’s overall conduct from anecdotes or one media story
- exclude sealed, juvenile, and otherwise confidential material
- be careful with person-level entity resolution across repeated criminal cases

Recommended first deliverable:

- one narrow sample set that links booking, case metadata, hearings, judge assignment, attorney roles, and final disposition

Recommended public-output metric family:

- arraignment and hearing volume by judge
- continuance frequency
- charge-to-disposition patterns
- dismissal, plea, conviction, and sentence distributions where public record supports them

### 7. Civil Litigation And Formal Oversight

Why it matters:

- public-law cases, injunctions, and oversight reports often constrain what local government claims it can do

This domain is already partially scoped in:

- `docs/judicial-and-oversight-extension.md`
- `docs/judicial-pressure-test-basket-source-bundle.md`
- `docs/judicial-pressure-test-basket-ingestion-checklist.md`

Recommended next deliverable:

- keep the current pressure-test basket, but do not let this domain crowd out administrative and criminal planning

### 8. State, Federal, And Quasi-Governmental Land Governance

Why it matters:

- a lot of Marin land, access, housing friction, and job impact sits outside ordinary city-council process
- local outcomes can be shaped by state, federal, or hybrid bodies with their own hearings, permits, plans, and veto points

Examples:

- California Coastal Commission
- Caltrans
- California State Parks
- National Park Service and GGNRA-style federal land managers
- special districts
- land-trust or conservancy organizations when they hold operational or quasi-public leverage

Primary record types:

- permit application
- coastal permit
- staff recommendation
- management plan
- easement document
- interagency agreement
- environmental review record
- board packet

New graph objects:

- `ExternalInstitution`
- `IntergovernmentalAgreement`
- `Easement`
- `ManagementPlan`

Key joins:

- governed `Place`
- local `Project`
- outside `Institution`
- local `Decision`
- affected `Issue`

Modeling note:

- a nonprofit land trust should not automatically be treated as a government body
- it should usually begin as an `Actor` with later claims or relationships showing contract, easement, advisory, or funding leverage

Recommended first deliverable:

- one locally salient thread where an outside body constrained housing, road, access, or park use

### 9. Transportation And Infrastructure Governance

Why it matters:

- some of the most visible daily-life impacts are roads, parking, circulation, transit, and right-of-way decisions
- the responsible institution is often not the one residents blame

Primary institutions:

- public works
- transportation authorities
- Caltrans
- special districts
- transit agencies

Primary record types:

- traffic study
- striping plan
- parking plan
- encroachment permit
- capital project sheet
- grant application
- right-of-way record

New graph objects:

- `Corridor`
- `CapitalProject`
- `TrafficStudy`

Key joins:

- affected `Place`
- responsible `Institution`
- approving `Decision`
- related `Funding` and `GrantProgram`

Recommended first deliverable:

- one street or parking decision with clear responsibility tracing across agencies

## Priority Order

If the goal is to make the graph broader without losing rigor, the next sequence should be:

1. permits, applications, denials, and appeals
2. criminal justice and court supervision
3. state, federal, and quasi-governmental land governance
4. transportation and infrastructure governance
5. deeper land-use and enforcement layers

That order gives the project:

- one strong administrative layer
- one strong public-safety and judicial-accountability layer
- one strong “outside the city hall walls” layer

## Immediate Modeling Implications

The current core graph can absorb these domains, but the next pass should add or sharpen:

- `Project`
- `Application`
- `Permit`
- `Appeal`
- `Charge`
- `CustodyEvent`
- `ReleaseDecision`
- `Disposition`
- `Sentence`
- `AttorneyRepresentation`
- `IntergovernmentalAgreement`
- `Easement`
- `ManagementPlan`

These do not require a new graph philosophy.
They require clearer subtype and join discipline inside the current model.
