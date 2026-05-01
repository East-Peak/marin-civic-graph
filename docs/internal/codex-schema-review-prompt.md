# Schema Review Prompt for Codex

## Context

We're building a civic-intelligence graph for Marin County, California (~260K people, ~10 cities + county government). The product is an invite-only investigation and transparency tool with:

- Neo4j graph database (AuraDB)
- Next.js frontend with entity pages, graph visualization (Cytoscape.js), data explorer, and AI chat
- Claude API integration for natural language → Cypher query translation and investigative reasoning
- Python ingestion pipeline with configurable source adapters

The data sources are all public records: city council meeting minutes, agendas, staff reports, campaign finance filings (Form 460, 497), economic interest disclosures (Form 700), behested payment reports (Form 803), court cases, permits, contracts, grants, budgets, and news articles.

The core investigation use cases:

1. **Follow the money**: "How is this campaign contributor connected to this permit approval?" — trace Donor → Contribution → Committee → Candidate → Vote → Project
2. **Conflict of interest**: "Did this councilmember vote on a project involving an entity they disclosed financial interest in?" — cross-reference Form 700 disclosures with voting records
3. **Temporal coincidence**: "Show me campaign contributions and government actions involving the same parties within 30 days of each other"
4. **Pattern detection**: "Which actors appear across multiple unrelated decisions, filings, and money flows?"
5. **Decision archaeology**: "What was discussed at the meeting where this decision was made? What was in the staff report? Who spoke during public comment?"
6. **Legal pressure mapping**: "Which court cases constrained which local decisions, and did the city comply?"

## The Proposed Schema (13 node types)

This was reduced from 28 types in an earlier iteration. The principle: each node type should represent something that is legally, temporally, or structurally distinct enough that making it a Neo4j label improves real investigation queries. Everything else becomes edges with properties, Organization subtypes, or metadata.

| Type | What it represents | Why it's a node type |
|------|-------------------|---------------------|
| **Person** | Individual human (elected official, donor, contractor, judge, etc.) | Legal identity — votes, files disclosures, holds seats, donates, testifies |
| **Organization** | Any non-person entity. Subtype property: government, nonprofit, business, political, court, department, commission | Counterparty in money flows, decisions, cases. Subtypes via property, not separate labels. |
| **Committee** | FPPC-regulated campaign finance entity | Legally distinct structure with registration, controlling officer, treasurer, election linkage. Core node in "follow the money" queries. Collapsing into Organization hides the campaign finance domain structure. |
| **Seat** | Elected or appointed position at an institution | Small count (~5-20 per jurisdiction) but high query value. "Who ran for District 4?" and "Who held this seat when this decision was made?" are core investigation queries. |
| **Election** | A bounded electoral contest | Temporal anchor for campaign finance. Ties together candidacies, filings, contributions, and results into a specific contest. Without it, campaign money loses its electoral context. |
| **Meeting** | A convened body session with date, attendees, agenda | The temporal container for decisions. Meetings have structure (consent calendar vs. public hearing vs. regular business) that matters for investigation. |
| **AgendaItem** | A discrete item on a meeting agenda | Not every agenda item produces a decision. Presentations, staff reports, public comments, ceremonial items are important context. "What else was discussed that night?" is a real investigation question. |
| **Decision** | An official action taken (vote, ordinance, resolution, contract award, motion) | The core governance action. Has vote tallies, outcomes, and links to the money/project/case that motivated it. |
| **Filing** | A disclosure or campaign finance document (Form 460, 700, 803, 497) | The evidentiary container for financial data. Different form types have different legal meanings. Links person/committee to specific disclosed transactions. |
| **MoneyFlow** | A financial transaction (contribution, expenditure, contract payment, grant) | The edge-with-weight in follow-the-money queries. Has amount, date, parties, source schedule, and filing provenance. |
| **Case** | Litigation (civil, criminal, appellate) | Legal proceedings that constrain or motivate government decisions. Has docket number, court, parties, status, timeline. |
| **Project** | A physical or policy initiative (development, infrastructure, shelter, permit application) | The thing decisions are about and money flows toward. Subsumes permits (a permit application is a project with subtype). |
| **Record** | A source document backing any of the above (PDF, HTML page, staff report, court order, minutes) | The evidence chain. Every fact in the graph must link to at least one Record. This is what makes the graph defensible for investigation. |

## What was collapsed (previously separate node types, now edges/properties)

| Former type | Where it went | Reasoning |
|------------|---------------|-----------|
| **Institution** | → Organization (subtype: government) | "City of San Rafael" and "Ritter Center" are both organizations. Government vs. nonprofit is a property. |
| **Program** | → Organization (subtype: program) or → Project | A municipal program is either an ongoing organizational entity or a project. Doesn't need its own type. |
| **SeatService** | → Edge (Person → Seat) with start_date, end_date properties | "Kate Colin held Mayor from 2022-2026" is a relationship, not an entity. Edge properties handle temporality. |
| **Candidacy** | → Edge (Person → Election) with seat_id, outcome properties | "Rachel Kertz ran for District 4 in 2024" is a relationship between a person and an election. |
| **CaseParticipation** | → Edge (Person/Organization → Case) with role property | "Downtown Streets Team is defendant in Boyd" is an edge with role=defendant. |
| **Proceeding** | → Property/sub-event on Case, or edge to Meeting | Court proceedings are temporal events within a case. At this scale, they don't need their own type. |
| **Agreement** | → Edge (Organization → Project/Organization) with amount, date properties | A contract is a relationship between parties about a project. |
| **Amendment** | → Edge (links to parent Agreement edge) or property | An amendment modifies a contract. Edge property or chained edge. |
| **EconomicInterestDisclosure** | → Filing (subtype: form_700) | A Form 700 is a filing. The disclosure type is a property on Filing. |
| **Place** | → Property (jurisdiction, address) on other nodes | "San Rafael" is a jurisdiction property, not a graph entity. |
| **Issue** | → Tag/label property on other nodes | "Homelessness" is a topic tag, not an entity. |
| **ValidationCheck** | Dropped (internal QA, not graph data) | Data quality checks are pipeline concerns, not graph nodes. |
| **Mention, Lead, Finding** | Dropped | Investigation workflow artifacts, not civic entities. |

## Your task

Stress-test this schema. Argue against it. Specifically:

1. **Write concrete Cypher queries** for each of the 6 investigation use cases listed above, using this 13-type schema. Identify where the schema makes queries awkward, unclear, or lossy.

2. **Argue for restoring any collapsed types.** If any of the collapsed types (SeatService, Agreement, Proceeding, Place, etc.) should be restored as nodes, make the case with a specific query that's materially harder without them.

3. **Argue for further collapse.** If any of the 13 types should be merged, make the case. Is Committee really distinct enough from Organization? Does Seat earn its keep? Is AgendaItem just noise?

4. **Identify missing types.** Is there a civic data concept that none of the 13 types covers? Think about: public comments, ballot measures, referendums, grand jury reports, audits, lobbying disclosures, subpoenas, FOIA requests.

5. **Test the Organization subtype approach.** The schema uses Organization with a subtype property for government bodies, nonprofits, businesses, departments, commissions, etc. Write 3 investigation queries that depend on organizational subtypes and evaluate whether this is cleaner or messier than having separate labels.

6. **Evaluate the edge-with-properties approach** for SeatService, Candidacy, Agreement, and CaseParticipation. Write a query that needs to join two of these (e.g., "which seat services overlap temporally with which agreements?") and evaluate whether the edge approach holds up or whether intermediate nodes would be cleaner.

Be specific. Use real Cypher. Name real entities from Marin County civic data (Kate Colin, Rachel Kertz, Boyd v. City of San Rafael, Form 460 filings, 350 Merrydale shelter, Downtown Library renovation, etc.). Don't hedge — make a recommendation.
