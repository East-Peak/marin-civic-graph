# Entity Glossary

Verified: April 10, 2026

This glossary is the working vocabulary for the project.

The goal is to stop schema drift before implementation starts.

## Core Objects

### Actor

An actor is any person or organization that can participate in process, money, advocacy, administration, or implementation.

Examples:

- elected official
- appointed commissioner
- city attorney
- nonprofit
- contractor
- donor
- PAC
- law firm
- reporter
- recurring public commenter

Rule:

- `Actor` is the broadest people-and-org bucket.
- `Institution` is not an actor unless there is a reason to treat the institution as an acting party in a case or contract.

### Institution

A formal public body or organizational unit with jurisdiction, authority, or an official role in governance.

Examples:

- Marin County Board of Supervisors
- San Rafael City Council
- San Rafael Planning Commission
- Marin County Community Development Agency

Rule:

- Use `Institution` for bodies, departments, commissions, courts, and boards.
- Use `Actor` for the people and outside organizations around them.

### Seat

A specific office or appointment slot inside an institution.

Examples:

- Mayor
- District 2 Councilmember
- Planning Commissioner Seat 4
- At-large appointee

Why it matters:

- appointments and elections attach cleanly to seats
- people can rotate through the same seat over time

### Meeting

A time-boxed public process event run by an institution.

Examples:

- regular city council meeting
- special board meeting
- planning commission hearing

### Agenda Item

A discrete item inside a meeting.

Examples:

- encampment ordinance amendment
- contract approval
- bike lane redesign
- public hearing on a project

Rule:

- most comments, votes, packets, and outcomes should attach to agenda items where possible, not just the parent meeting

### Decision

A formal outcome or action.

Examples:

- vote to adopt an ordinance
- approval of a contract
- denial of an appeal
- adoption of a resolution
- authorization to litigate or settle

Rule:

- not every agenda item results in a decision
- not every decision happens inside a meeting

### Record

A source artifact that can evidence an object or event.

Examples:

- ordinance
- resolution
- agenda
- packet
- minutes
- video
- staff report
- contract
- Form 460
- Form 700
- Form 803
- 990
- article

Rule:

- records are evidence, not conclusions
- `Record` is the umbrella node
- older notes that say `Document` should be read as the early name for this concept

Suggested classification:

- `meeting_record`
- `legislative_record`
- `media_record`
- `financial_record`
- `contract_record`
- `legal_record`
- `program_record`

Examples:

- Marin IJ article = `media_record`
- ordinance / resolution = `legislative_record`
- minutes / packet = `meeting_record`

### MoneyFlow

A normalized record of money moving from one actor to another, or being obligated by an institution.

Examples:

- campaign contribution
- independent expenditure
- city contract
- county grant
- behested payment

Rule:

- use one broad object first
- subtype it later if needed

### Issue

A recurring policy area or topic cluster.

Examples:

- homelessness
- encampments
- parking
- public safety
- housing
- active transportation

Rule:

- issues are cross-cutting tags, not institutions and not events

### Program

An ongoing operational effort that persists across multiple decisions, records, and updates.

Examples:

- sanctioned camping program
- outreach team
- work program
- shelter operation

Rule:

- use `Program` when the thing being tracked has operators, updates, and implementation over time
- do not collapse a long-running program into one decision or one place

### Case

A lawsuit or other formal dispute that appears across many records and process events.

Examples:

- `Boyd v. City of San Rafael`
- `City of Grants Pass v. Johnson`

Rule:

- use `Case` for the durable dispute object
- use `CaseParticipation` for the role an actor or institution played in it

### Place

A geographic object relevant to governance or impact.

Examples:

- Marin County
- San Rafael
- Albert Park
- downtown corridor
- project parcel
- encampment site

Rule:

- use `Place` whenever geography matters to jurisdiction, impact, or repeated conflict

### RecordSegment

A bounded part of a larger record that matters operationally.

Examples:

- ordinance pages inside a packet
- contract exhibit inside a resolution bundle
- quote block inside an article
- correspondence section inside a staff report

Rule:

- use `RecordSegment` when the parent record still matters
- promote a segment into its own `Record` when users will need to browse, cite, or relate to it directly

## Event Objects

### PublicComment

A statement by a speaker in a meeting context or equivalent public process.

Fields worth preserving:

- speaker raw name
- resolved actor if known
- self-identified affiliation
- stance
- summary
- exact quote where safely available

### VoteCast

An individual recorded vote by a person or seat.

Rule:

- the overall `Decision` is separate from the individual `VoteCast` records

### Appointment

A record that someone was appointed or elected into a seat.

### Membership

A record that an actor belongs to or serves within an organization or institution.

Examples:

- board member
- executive director
- treasurer
- commissioner

### CaseParticipation

A record that an actor or institution participated in litigation or another formal case posture.

Examples:

- plaintiff
- defendant
- amicus
- counsel

### Proceeding

A bounded court event inside a case.

Examples:

- arraignment
- bail review
- pretrial conference
- plea hearing
- sentencing hearing

Rule:

- use `Proceeding` when the date, judge, or hearing type matters
- do not collapse all case activity into one `Case`

### Charge

A criminal count or allegation attached to a prosecution.

Rule:

- distinguish booked charges from filed charges and later amended charges
- do not assume the booking stage and the disposition stage describe the same charge object

### CustodyEvent

A jail or custody state change tied to a person.

Examples:

- booking
- admission
- release on bail
- release on own recognizance
- remand

### ReleaseDecision

A judicial or custody decision about detention, bail, or release conditions.

Rule:

- use `ReleaseDecision` for the outcome
- use `CustodyEvent` for the actual custody state change

### AttorneyRepresentation

A prosecutor or defense role inside a case or proceeding.

Examples:

- deputy district attorney
- public defender
- private defense counsel

Rule:

- keep attorney roles explicit rather than leaving them as loose mentions

### Disposition

The formal outcome of a case or charge.

Examples:

- dismissed
- plea
- convicted
- acquitted
- diversion

### Sentence

The punishment or supervision result that follows a conviction or plea.

Examples:

- jail term
- probation
- fine
- restitution
- time served

### Mention

A record that an actor, institution, place, or issue was named, quoted, paraphrased, or described in a record.

Examples:

- quoted resident
- nonprofit spokesperson
- attorney for plaintiffs
- city spokesperson
- place named in minutes
- organization named in a staff report

Why it matters:

- local media often introduces actors without clearly surfacing their deeper affiliations
- records in general often introduce names before the system resolves them against other evidence

Suggested fields:

- raw name string
- role label as printed
- affiliation label as printed
- quote excerpt
- resolved actor if known
- confidence

Note:

- older notes may still say `ArticleMention`
- treat that as the media-specific version of `Mention`

## Evidence Terms

### Lead

A potentially useful pointer that is not yet strong enough to promote into the main graph.

Examples:

- anecdote from a resident
- claim in an essay
- unverified social-media assertion

Rule:

- leads can guide research
- leads should not be treated as facts

### Claim

A candidate assertion derived from one or more sources.

Examples:

- person X is affiliated with organization Y
- organization Y received grant Z
- speaker X appeared on issue A three times
- person X was described as an unaffiliated resident in an article but appears elsewhere as an NGO activist or recurring advocate

Rule:

- claims should be promotable or rejectable based on evidence tier
- article-based affiliation claims should usually require corroboration unless the affiliation is explicit in the article itself

### Evidence Tier

Evidence quality ranking used to decide what becomes graph truth.

- `Tier A`: filings, signed contracts, adopted minutes, court opinions, disclosure forms
- `Tier B`: agendas, packets, official pages, meeting videos, clerk records
- `Tier C`: local media with concrete sourcing
- `Tier D`: commentary and secondary analysis
- `Tier E`: tips, anecdotes, unverified claims

## Working Modeling Rules

### Rule 1

Prefer event nodes over direct edges when date, amount, role, or evidence matter.

### Rule 2

Store observable facts, not summary accusations.

### Rule 3

Treat influence as a derived view, not a primitive field.

### Rule 4

Keep institutions, actors, issues, and places distinct even when they are strongly associated in practice.
