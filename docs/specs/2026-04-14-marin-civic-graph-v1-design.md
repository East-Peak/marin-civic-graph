# Marin Civic Graph v1 — Design Spec

**Date:** 2026-04-14
**Status:** Draft (post-Codex review)
**Author:** Claude (Opus), with Stuart Watson
**Reviewed by:** Codex (adversarial review, 2026-04-14)

## 1. Product Vision

A civic-intelligence tool for Marin County that makes local government decision-making legible and investigable through primary-source public records. Invite-only access — usable both as a shareable transparency tool and a personal investigation workbench.

**Core thesis:** If you can ingest meeting minutes, rulings, injunctions, permits, contributions, and grants from city and county governments into a well-structured graph, you can query how and why decisions were made — and eventually surface fraud, conflicts of interest, and suspicious patterns.

**Inspirations:** SF Gov Graph (CivLab), House of the People Gap Tracker, Machinery of Government UK.

**Scope:** Marin County (~260K people, ~10 cities + county government). San Rafael is the most complete jurisdiction. v1 gets the existing data into a queryable product; expansion to other Marin cities follows.

## 2. Architecture Overview

```
Raw Captures (data/raw/)           Python Ingestion Pipeline
    HTML, PDF, JSON, CSV    ──>    Source Adapters
                                          │
                                          ▼
                                  Normalized Bundles
                                  (promotion, evidence,
                                   object boundaries)
                                          │
                                          ▼
                                   Neo4j AuraDB
                                   (graph database)
                                          │
                                          ▼
                              Next.js App (Vercel)
                             ┌────────────────────────┐
                             │  Entity Pages           │
                             │  Graph Visualizations   │
                             │  Data Explorer          │
                             │  AI Chat Interface      │
                             └────────────────────────┘
                                          │
                                          ▼
                                   Claude API
                              (Cypher gen + reasoning)
```

**Stack:**

| Layer | Technology |
|---|---|
| Database | Neo4j AuraDB |
| Frontend | Next.js + Tailwind CSS |
| Graph visualization | Cytoscape.js + D3.js (radial, timeline, network) |
| API | Next.js API routes + Neo4j JavaScript driver |
| AI | Claude API with prompt caching |
| Auth | Invite-code or allowlist (simple, not a full auth system) |
| Deployment | Vercel (app) + Neo4j AuraDB (database) |
| Ingestion | Python scripts running locally on Mac mini |
| Offline cache | SQLite read-model cache for offline entity browsing |

## 3. Data Model — 21 Core Node Types

### Design Principles

- Each node type represents something legally, temporally, or structurally distinct enough that making it a Neo4j label improves real investigation queries.
- Organization uses multi-label subtypes (e.g., `:Organization:Government`, `:Organization:Nonprofit`) for both uniform and specific querying.
- Every fact links to at least one Record node (evidence chain).
- ID convention preserved from existing project: human-readable, deterministic, type-prefixed (e.g., `person-kate-colin`, `decision-2024-08-19-resolution-15336`).

### Node Types

| # | Type | What it represents | Key properties |
|---|------|-------------------|----------------|
| 1 | **Person** | Individual human | name, aliases, role_labels |
| 2 | **Organization** | Non-person entity (multi-label: Government, Nonprofit, Business, Political, Court, Department, Commission) | name, subtype, jurisdiction_id |
| 3 | **Committee** | FPPC-regulated campaign finance entity | name, fppc_id, controlling_person_id, treasurer, election_id |
| 4 | **Seat** | Elected or appointed position | name, seat_type, institution_id, district |
| 5 | **SeatService** | Bounded period a person holds a seat | started_at, ended_at, service_type (elected/appointed), election_id |
| 6 | **Election** | A bounded electoral contest | election_date, election_type, jurisdiction_id |
| 7 | **Candidacy** | A person running for a seat in an election | outcome, party |
| 8 | **Meeting** | A convened body session | meeting_date, meeting_type, title |
| 9 | **AgendaItem** | A discrete item on a meeting agenda | item_number, section_number, title, heading |
| 10 | **Decision** | An official action taken | decided_at, decision_type, status, vote_summary |
| 11 | **Filing** | A disclosure or campaign finance document | filing_type (form_460/700/803/497), signed_at, period_start, period_end |
| 12 | **MoneyFlow** | A financial transaction | amount, flow_date, flow_type, source_schedule, parse_confidence |
| 13 | **Case** | Litigation | case_type, docket_number, filed_at, closed_at, status |
| 14 | **Proceeding** | A court event within a case | proceeding_type, date, outcome |
| 15 | **Project** | A physical or policy initiative (includes permits) | project_type, status, address |
| 16 | **Program** | An ongoing governmental program or policy | program_type, status |
| 17 | **Agreement** | A contract, grant, or MOU | agreement_type, amount, effective_date |
| 18 | **Amendment** | A modification to an agreement | amendment_type, effective_date |
| 19 | **Record** | A source document backing any of the above | record_type, artifact_path, source_url, captured_at |
| 20 | **Place** | A jurisdiction or location | name, place_type (city/county/address/state) |
| 21 | **Issue** | A policy topic for cross-thread queries | name, issue_type, aliases |

### QA Lane (separate from core ontology)

| Type | Purpose |
|------|---------|
| **ValidationCheck** | Data quality flags. Not surfaced in normal entity traversal. Queryable on demand for "what doesn't reconcile?" workflow. Kept in a separate QA subgraph, not mixed into core entity queries. |

### Deferred Types

| Type | When to add |
|------|------------|
| **PublicComment** | When structured public comment data is available from meeting sources |
| **BallotMeasure** | When ballot measure data enters scope |

### Key Relationship Types

Governance:
- `(:Person)-[:CAST_VOTE {vote: yes/no/absent/abstain}]->(:Decision)`
- `(:Decision)-[:AT_MEETING]->(:Meeting)`
- `(:Decision)-[:ABOUT_ITEM]->(:AgendaItem)`
- `(:Decision)-[:DECIDED_BY]->(:Organization:Government)`
- `(:AgendaItem)-[:PART_OF]->(:Meeting)`
- `(:Decision)-[:ABOUT_PROJECT]->(:Project)`
- `(:Decision)-[:ABOUT_PROGRAM]->(:Program)`

Seats and elections:
- `(:SeatService)-[:HELD_BY]->(:Person)`
- `(:SeatService)-[:FOR_SEAT]->(:Seat)`
- `(:SeatService)-[:RESULT_OF]->(:Election)`
- `(:Seat)-[:AT_INSTITUTION]->(:Organization:Government)`
- `(:Candidacy)-[:BY_PERSON]->(:Person)`
- `(:Candidacy)-[:FOR_SEAT]->(:Seat)`
- `(:Candidacy)-[:IN_ELECTION]->(:Election)`

Campaign finance:
- `(:MoneyFlow)-[:FROM_SOURCE]->(:Person|:Organization|:Committee)`
- `(:MoneyFlow)-[:TO_TARGET]->(:Committee|:Person|:Organization)`
- `(:MoneyFlow)-[:DISCLOSED_IN]->(:Filing)`
- `(:Filing)-[:FILED_BY]->(:Person|:Committee)`
- `(:Filing)-[:FOR_ELECTION]->(:Election)`
- `(:Committee)-[:CONTROLLED_BY]->(:Person)`

Legal:
- `(:Proceeding)-[:PART_OF]->(:Case)`
- `(:Case)-[:HEARD_IN]->(:Organization:Court)`
- `(:Person|:Organization)-[:PARTY_TO {role: plaintiff/defendant/amicus}]->(:Case)`
- `(:Case)-[:CONSTRAINS]->(:Decision)`

Financial:
- `(:Agreement)-[:BETWEEN]->(:Organization)`
- `(:Agreement)-[:FOR_PROJECT]->(:Project)`
- `(:Amendment)-[:AMENDS]->(:Agreement)`
- `(:MoneyFlow)-[:UNDER_AGREEMENT]->(:Agreement)`

Evidence (universal):
- `(:*)-[:EVIDENCED_BY]->(:Record)`

Jurisdiction and topic:
- `(:*)-[:IN_JURISDICTION]->(:Place)`
- `(:*)-[:RELATES_TO_ISSUE]->(:Issue)`

## 4. Ingestion Pipeline

### Migration from current graph-v1 to settled ontology

The current projected graph uses labels that don't match the settled schema. Before anything else, a migration step must remap every node type, ID prefix, and relationship type. The migration script runs once, produces a new set of normalized bundles conforming to the settled schema, and those bundles feed the Neo4j loader.

**Node migration mapping:**

| Current label | Target label | ID rewrite | Property rewrites | Fate |
|---|---|---|---|---|
| Actor (actor_type=person) | Person | `actor-` → `person-` | `observed_labels` → `aliases` | Survives |
| Actor (actor_type=business\|organization\|political_committee) | Organization | `actor-` → `org-` | `actor_type` → multi-label subtype (Business, Nonprofit, Political) | Survives |
| Institution | Organization:Government | `inst-` → `org-` | `institution_type` → `subtype` property | Survives |
| Committee | Committee | No change | No change | Survives |
| Seat | Seat | No change | `institution_id` refs remapped to `org-` prefix | Survives |
| SeatService | SeatService | No change | Actor refs remapped to `person-` prefix | Survives |
| Election | Election | No change | No change | Survives |
| Candidacy | Candidacy | No change | Actor refs remapped to `person-` prefix | Survives |
| Meeting | Meeting | No change | Institution refs remapped to `org-` prefix | Survives |
| AgendaItem | AgendaItem | No change | No change | Survives |
| Decision | Decision | No change | Institution refs remapped to `org-` prefix; actor vote refs remapped to `person-` prefix | Survives |
| Filing | Filing | No change | Actor refs remapped to `person-` prefix | Survives |
| EconomicInterestDisclosure | Filing | `eid-` → `filing-` | Add `filing_type: form_700`; `filer_actor_id` → `filed_by` with `person-` prefix | Merged into Filing |
| MoneyFlow | MoneyFlow | No change | Actor/committee refs remapped | Survives |
| Case | Case | No change | Institution refs remapped to `org-` prefix | Survives |
| Proceeding | Proceeding | No change | No change | Survives |
| CaseParticipation | _(dropped as node)_ | N/A | `role` becomes edge property on `PARTY_TO` | Collapsed into edge |
| Project | Project | No change | No change | Survives |
| Program | Program | No change | Institution refs remapped to `org-` prefix | Survives |
| Agreement | Agreement | No change | Institution refs remapped to `org-` prefix | Survives |
| Amendment | Amendment | No change | No change | Survives |
| Record | Record | No change | No change | Survives |
| Place | Place | No change | No change | Survives |
| Issue | Issue | No change | No change | Survives |
| ValidationCheck | ValidationCheck | No change | No change | Moves to QA subgraph |

**Relationship rewrites:**

| Current relationship | Target relationship | Notes |
|---|---|---|
| HELD_BY_ACTOR | HELD_BY | Target remapped to Person |
| CONTROLLED_BY_ACTOR | CONTROLLED_BY | Target remapped to Person |
| FILED_BY_ACTOR | FILED_BY | Target remapped to Person |
| DECIDED_BY_INSTITUTION | DECIDED_BY | Target remapped to Organization:Government |
| RELATES_TO_INSTITUTION | AT_INSTITUTION | Target remapped to Organization:Government |
| HEARD_IN_COURT | HEARD_IN | Target remapped to Organization:Court |
| CAST_VOTE_ON | CAST_VOTE | Source remapped to Person |
| All `_ACTOR` suffix edges | Drop suffix | Source/target remapped as appropriate |
| CaseParticipation edges | PARTY_TO {role} | Participation node properties become edge properties |

**ID cross-reference table:** The migration script must produce a deterministic `old_id → new_id` mapping file so that any downstream references (in bundles, evidence links, or external notes) can be resolved. This mapping is committed to the repo.

**Preservation rule:** Every node and edge in the current graph-v1 must map to the settled schema or be explicitly accounted for in this table. No silent drops.

### v1: Bulk import via normalized bundles

The import path is: **existing normalized bundles → migration script → settled-schema bundles → Neo4j loader.**

The loader must use:
- Batched `UNWIND` writes (not individual `MERGE` per node)
- Unique constraints on all node type IDs
- The import manifest (`registry/import-manifest.yaml`) as the authoritative source for what gets loaded

The existing raw captures are the underlying asset:
- 263 San Rafael council meeting pages (2019-2026)
- 1,085 Form 700 filing rows
- Campaign filing inventories and Form 460 captures
- Court documents (Boyd, Grants Pass)
- Procurement, permit, and project captures

### v2: Configurable adapter framework

Source adapters configured via YAML, one adapter type per source platform:

| Adapter Type | Sources it handles |
|---|---|
| GranicusAdapter | Legislative management systems (council meetings, agendas, minutes) |
| NetFileAdapter | Campaign finance and disclosure portals |
| LaserficheAdapter | Document management systems |
| PDFAdapter | Direct PDF capture and text extraction |
| HTMLAdapter | Generic web page capture |
| APIAdapter | Structured API/export endpoints |

Each source instance is a YAML entry. Adding a new city's council is configuration, not code.

**Normalized bundles are preserved as a first-class layer in v2.** Adapters write raw and extracted artifacts; parsers produce normalized bundles with promotion state, object-boundary judgment, and evidence discipline; the loader reads bundles and writes to Neo4j. Bundles are the audit trail between raw artifacts and graph nodes. Skipping them would force every adapter to re-implement promotion filtering, identity resolution, and evidence linking.

Identity resolution runs as a post-processing pass after each batch, matching new names against existing Person/Organization nodes.

### Neo4j Indexing Plan

Before the app goes live, AuraDB must have:

**Unique constraints (one per node type):**
- All 21 core types: unique constraint on `id` property

**Full-text indexes:**
- Names and display labels across Person, Organization, Committee, Project, Program, Case, Agreement

**Property indexes for query performance:**
- `Meeting.meeting_date`
- `Decision.decided_at`
- `MoneyFlow.flow_date`
- `MoneyFlow.amount`
- `Filing.signed_at`
- `Election.election_date`
- `Proceeding.date`
- `Agreement.effective_date`
- `MoneyFlow.flow_type`
- `Filing.filing_type`
- `Decision.decision_type`

## 5. Product Surfaces

### 5a. Entity Pages

Two tiers of entity pages, based on current data richness:

**Tier 1 — Rich templates** (full page with hero visualization, key facts, connections, timeline, evidence):
- Person, Decision, Project, Program, Case, Meeting, Filing, Committee

**Tier 2 — Lightweight pages** (header, key facts, connections list, evidence links):
- Organization, Seat, SeatService, Election, Candidacy, AgendaItem, MoneyFlow, Proceeding, Agreement, Amendment, Record, Place, Issue

All pages live at `/{type}/{id}` (e.g., `/person/kate-colin`, `/project/350-merrydale-interim-shelter`).

Tier 1 pages include:
- **Header:** name, type badge, jurisdiction, key identifiers
- **Hero visualization:** radial/orbital graph diagram showing the entity's connections, color-coded by node type
- **Key facts panel:** type-specific summary (for a Person: current seat, term, filings; for a Project: status, total money, decisions)
- **Connections:** cards for the most important related entities, grouped by relationship type
- **Timeline:** chronological view of all activity involving this entity
- **Evidence drawer:** expandable section showing source Record nodes for any fact on the page

Tier 2 pages include:
- **Header:** name, type badge, jurisdiction
- **Key facts panel:** type-specific summary
- **Connections list:** linked entities with relationship type
- **Evidence links:** source Record nodes

### 5b. Graph Visualizations (first-class, not afterthought)

**v1 visualization set (three types):**

**Radial/orbital diagrams (hero visualization on entity pages)**
- Center any entity, show connections in concentric rings by hop distance
- Color-coded by node type, sized by importance (money amount, connection count)
- Interactive: click a node to re-center, hover for details
- The "share with friends" visualization — clean, beautiful, immediately legible
- Most compelling for: Kate Colin, Merrydale, sanctioned camping, Resolution 15336, Boyd

**Timeline ribbons (temporal analysis)**
- Horizontal timeline with events plotted chronologically
- Relationship lines connect temporally related events
- Highlight temporal coincidences (contribution + permit approval within N days)
- Most compelling for: Boyd/Grants Pass legal chain, Merrydale decision sequence, sanctioned camping/ordinance implementation history

**Network explorer (investigation tool)**
- Full-screen force-directed graph
- Start from any entity, expand outward
- Path finding between two entities
- Subgraph extraction (select nodes, see only their connections)
- Temporal filtering (time slider)
- Edge type filtering
- Hop and node-type limits to prevent runaway traversal
- Save investigation views (persisted to user's session, not shared)

**v2 visualization set (deferred):**

**Sankey/flow diagrams (money flows)**
- Deferred because current money data is 157 flows across mixed patterns — compelling only when tightly filtered or after broader campaign finance ingest
- Show how dollars move from donors -> committees -> candidates -> decisions -> projects

**Org structure trees (machinery of government)**
- Deferred because the graph doesn't yet carry rich reporting hierarchy
- Council -> committees -> departments -> programs

### 5c. Data Explorer

Tabular/filterable interface for structured queries.

**Predefined query templates (based on actual data richness):**

1. San Rafael decisions since 2019 — filter by meeting date, institution, issue, linked project/program
2. Money flows over $X by year, flow type, and related decision/project
3. Filings by person or committee across 2020-2026, grouped by filing type
4. Current officeholders and their Form 700/803 coverage
5. Agreements and amendments for a project (especially Downtown Library and Merrydale)
6. Legal proceedings affecting a local project/program (Boyd/Grants Pass-linked threads)
7. Evidence records supporting a decision, project, or case
8. Local pressure ranking for San Rafael threads (from QX-001 outputs)
9. Campaign money within N days of a local decision for bounded San Rafael threads
10. QA-only: unresolved validation/reconciliation gaps

Features:
- Column sorting, date range filtering, amount thresholds
- Click any row to navigate to the entity page
- Export to CSV

### 5d. AI Chat Interface

**This is the hardest component in the spec.** It should be built last, after entity pages, visualizations, and data explorer are working against real data.

Chat panel available from any page. Context-aware — inherits the current entity/page context.

**Three modes (system selects automatically):**

1. **Query mode:** natural language -> Cypher -> structured results (tables, charts, graph views). "Show me all campaign contributions to council members from contractors who won city bids."

2. **Context mode:** pulls 2-3 hop subgraph around current entity, Claude reasons over actual data and returns narrative explanation with Record citations. "What's interesting about this project?"

3. **Investigation mode:** user is exploring a thread across multiple entities. Claude has the current session context (recent queries, viewed entities) and can suggest follow-up queries, cross-reference across domains, generate investigation summaries, and flag gaps in the data. "This contribution and this permit approval are two weeks apart. What other connections exist between these parties?"

**Guardrails for AI-generated Cypher:**
- Allowed query patterns: whitelist of Cypher templates the AI can use, parameterized by node type, property filters, and traversal depth
- Max traversal depth: 4 hops by default, 6 with explicit user request
- Citation enforcement: every AI claim must reference at least one Record node ID; claims without evidence are flagged as unsupported
- Ambiguity handling: when a query could match multiple entities, the AI asks for clarification rather than guessing
- Cost controls: prompt caching for schema + session context; timeout on Cypher execution

**Constraints:**
- Every AI claim must cite source Record nodes
- AI explicitly flags when data is incomplete or ambiguous
- Prompt caching keeps schema + session context warm for responsive interaction

## 6. Auth and Access

Simple invite-only access. Not a full auth system.

Options (pick one during implementation):
- Invite codes: Stuart generates a code, shares with a friend, they get access
- Email allowlist: Stuart adds emails, users sign in with a magic link
- Clerk or similar lightweight auth provider if more structure is needed later

The key requirement: Stuart controls who sees it. No public access, no self-signup.

Note: saved investigation views (from network explorer) are persisted per-user session, not shared. This avoids the need for multi-user collaboration, ownership, or revocation logic in v1.

## 7. Deployment

| Component | Where | Notes |
|---|---|---|
| Next.js app | Vercel (Pro plan) | Stuart already has Vercel Pro. maxDuration up to 300s for AI queries. |
| Neo4j | AuraDB (managed) | Dedicated instance. Handles backups, scaling. |
| Python ingestion | Mac mini (local) | Runs on demand or on a schedule. Writes to AuraDB over network. |
| SQLite cache | Mac mini (local) | Read-model cache for offline entity browsing. Contains denormalized entity summaries and connection lists — not a full graph mirror. |

### Operational concerns

- **Backup/recovery:** Normalized bundles and raw artifacts on the Mac mini are the source of truth. AuraDB can be rebuilt from bundles at any time. AuraDB's own backup features provide additional safety.
- **Monitoring:** Log ingestion runs (success/failure, node/edge counts). Log AI query failures and timeouts. Alert on AuraDB connectivity issues.
- **Data refresh:** v1 is a one-time import. v2 adds scheduled adapter runs. No real-time ingestion in v1.
- **Secret management:** AuraDB credentials and Claude API key stored as Vercel environment variables. Not committed to repo. Python ingestion scripts use local environment variables on Mac mini.
- **Artifact storage:** Raw PDFs and HTML stay in the repo's `data/raw/` directory on the Mac mini. Not uploaded to AuraDB or Vercel. If the repo grows large, large binaries can be moved to external storage (rclone) with path references preserved.

## 8. What's Explicitly Out of Scope for v1

- Public self-signup or broad distribution
- Coverage beyond San Rafael + Marin County (jurisdictions added in v2+)
- Real-time data ingestion or live monitoring
- The general-purpose adapter framework (v1 uses one-time bulk import from existing bundles)
- PublicComment and BallotMeasure node types
- Mobile optimization
- Multi-user collaboration features (shared investigations, comments)
- Sankey flow diagrams and org structure tree visualizations (v2 — radial diagrams, timelines, and network explorer are the v1 set)

## 9. Success Criteria

### v1-core (launchable without AI)

1. Migration from current graph-v1 labels to settled ontology is complete and loaded into AuraDB
2. All Neo4j indexes and constraints are in place
3. Tier 1 entity pages are working for Person, Decision, Project, Program, Case, Meeting, Filing, Committee — with hero radial visualization
4. Tier 2 entity pages are working for remaining types — lightweight but functional
5. Timeline visualization is working for at least Boyd, Merrydale, and sanctioned camping threads
6. Network explorer supports path finding, subgraph extraction, and temporal filtering
7. Data explorer can run the 10 predefined queries with filtering and CSV export
8. Auth is in place — Stuart can share a link with a friend and they can browse the graph
9. Deployment is live on Vercel + AuraDB

### v1-complete (AI-assisted investigation)

10. AI chat can answer the 6 core investigation use cases with Record citations
11. Cypher guardrails are enforced (template whitelist, depth limits, citation checks)
12. Stuart can run an investigation session using the chat + graph explorer

v1-core is the release gate. v1-complete follows. The hardest component (AI chat) does not block launch of the browsing and exploration tool.

## 10. Investigation Use Cases (acceptance tests for AI layer)

These are the 6 queries the AI chat must handle correctly:

1. **Follow the money:** "How is this campaign contributor connected to this permit approval?"
2. **Conflict of interest:** "Did this council member vote on a project involving an entity they disclosed financial interest in?"
3. **Temporal coincidence:** "Show me campaign contributions and government actions involving the same parties within 30 days of each other"
4. **Pattern detection:** "Which actors appear across multiple unrelated decisions, filings, and money flows?"
5. **Decision archaeology:** "What was discussed at the meeting where this decision was made? What was in the staff report?"
6. **Legal pressure mapping:** "Which court cases constrained which local decisions, and did the city comply?"

## 11. Build Order

Based on dependencies and risk. Auth is a release gate, not a floating concern.

**Phase 1: Foundation**
1. **Migration + Neo4j load** — must come first, everything depends on it
2. **API layer** — Next.js API routes that query Neo4j, serve entity data

**Phase 2: Core browse experience**
3. **Tier 1 entity pages** — the core browsing experience
4. **Radial visualization** — hero visualization for entity pages
5. **Tier 2 entity pages** — lightweight pages for remaining types

**Phase 3: Exploration tools**
6. **Data explorer** — predefined queries, filtering, export
7. **Timeline visualization** — temporal analysis for legal and decision threads
8. **Network explorer** — investigation graph tool

**Phase 4: Release gate**
9. **Auth** — invite-only access, must be in place before any sharing

_v1-core ships here._

**Phase 5: AI layer**
10. **AI chat** — built last because it's the hardest and benefits from all other surfaces being stable

_v1-complete ships here._
