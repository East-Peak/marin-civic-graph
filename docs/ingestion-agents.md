# Ingestion Agents

Date drafted: April 10, 2026

This document sketches the first operating model for scraping and ingestion agents.

The goal is to define how the system should collect, parse, normalize, reconcile, and promote public-source data without collapsing into one giant brittle scraper.

## Core Principle

Treat ingestion as a staged pipeline with narrow responsibilities.

Do not let a single agent:

- discover a source
- scrape it
- infer entities
- update the graph
- and publish conclusions

all in one step.

That is how data rot and hallucinated structure creep in.

## Design Goals

- prefer structured official sources over browser automation
- preserve raw source artifacts before normalization
- make every promotion step inspectable
- isolate brittle site-specific logic
- keep LLM use bounded to extraction and reconciliation support, not core truth assignment
- make re-runs idempotent
- support both scheduled refresh and one-off backfills

## Pipeline Stages

The ingestion pipeline should have six logical stages.

1. `Discover`
2. `Fetch`
3. `Extract`
4. `Normalize`
5. `Resolve`
6. `Promote`

The output of each stage should be persisted before the next stage runs.

## Agent Catalog

### 1. Source Scout Agent

Purpose:

- find and verify source surfaces for a jurisdiction or institution
- classify source type and update the source registry

Inputs:

- seed URL
- jurisdiction or institution context
- existing source registry entries

Outputs:

- source manifest entry
- source type classification
- fetch strategy recommendation
- freshness expectations
- change warnings if the surface moved or broke

Typical classifications:

- static HTML
- RSS / Atom
- JSON API
- PDF index page
- Legistar / Granicus
- NetFile / campaign portal
- form-driven site
- JS-heavy public site

Important:

- this agent does not parse substantive civic content
- it only describes the source surface and how to approach it

### 2. Surface Mapper Agent

Purpose:

- map a discovered source surface into a stable extraction plan

Inputs:

- source manifest entry
- sample HTML / JSON / PDF index

Outputs:

- extraction recipe
- pagination strategy
- selectors or endpoint templates
- attachment discovery rules
- canonical identifier logic

Why it exists:

- one source page may expose several useful objects:
  meeting row, agenda PDF, packet PDF, minutes PDF, video link, attachment links

The surface mapper decides where those objects live.

### 3. Fetch Agent

Purpose:

- retrieve raw source artifacts and persist them unchanged

Inputs:

- source manifest
- extraction recipe

Outputs:

- raw HTML snapshots
- raw JSON responses
- downloaded PDFs
- metadata about fetch time, HTTP status, checksum, and discovered child URLs

Strategy order:

1. direct API / JSON
2. RSS or XML
3. static HTML
4. browser automation only if required

Important:

- the fetch agent should never write graph entities directly
- it only writes raw artifacts plus fetch metadata

### 4. Browser Retrieval Agent

Purpose:

- handle sites that require JavaScript rendering, click-through discovery, or awkward pagination

Inputs:

- source manifest entry marked as browser-required
- browser recipe from surface mapping

Outputs:

- rendered HTML snapshot
- discovered download links
- downloaded files
- screenshots when needed for debugging

Use cases:

- pages that render meeting rows client-side
- buried document links
- public portals with JS routing

Guardrails:

- use only when simpler fetch strategies fail
- cache aggressively
- keep runs low-frequency

### 5. Document Extract Agent

Purpose:

- turn raw artifacts into structured extracted content

Inputs:

- raw HTML
- raw JSON
- PDF files
- video / transcript files if available

Outputs:

- extracted text
- section structure
- candidate meetings
- candidate agenda items
- candidate vote tables
- candidate speaker/comment blocks
- candidate money tables
- candidate quote / mention blocks from articles
- extraction confidence

This is the main place for bounded LLM assistance.

Safe LLM use here:

- classify sections in a packet
- map table rows into typed fields
- summarize a comment block for indexing
- infer whether a document is an agenda, minutes, packet, or contract
- isolate quoted speakers and stated affiliations in local news articles

Unsafe LLM use here:

- assigning causal blame
- inventing missing vote outcomes
- merging people automatically without evidence

### 6. Media Attribution Agent

Purpose:

- convert article quote blocks and reported roles into resolvable actor mentions

Inputs:

- extracted article text
- quote blocks
- bylines and metadata
- existing actor registry

Outputs:

- `ArticleMention` candidates
- actor-role candidates
- affiliation claims
- ambiguity flags for review

Primary use case:

- local media, especially subscription local media, often quotes someone as a resident, neighbor, advocate, or volunteer without fully surfacing that person’s recurring organizational role

This agent should preserve both:

- how the article framed the person
- what the system can later corroborate from other sources

Guardrails:

- article framing alone should not silently rewrite canonical affiliations
- explicit article labels can be stored as article-scoped facts
- stronger cross-source claims should require corroboration

### 7. Normalization Agent

Purpose:

- convert extracted content into canonical object candidates

Inputs:

- extracted document output
- source metadata

Outputs:

- candidate `Meeting`
- candidate `AgendaItem`
- candidate `Decision`
- candidate `Document`
- candidate `PublicComment`
- candidate `MoneyFlow`
- canonical timestamps
- canonical URLs
- source-tier assignment

Rule:

- normalization creates candidates, not final truth

### 8. Entity Resolution Agent

Purpose:

- determine whether names and organizations map to existing canonical actors or institutions

Inputs:

- normalized candidates
- current canonical registry
- alias tables

Outputs:

- matched entity ID
- proposed new entity
- alias additions
- confidence score
- unresolved queue item when ambiguous

Examples:

- `City of San Rafael` vs `San Rafael` vs `San Rafael City Council`
- `Downtown Streets Team` vs `DST`
- `Maria B.` on a speaker card vs full name elsewhere
- quoted "Mill Valley resident" vs known activist / nonprofit affiliate appearing in multiple records

Important:

- ambiguous merges should go to review, not auto-promote

### 9. Promotion Agent

Purpose:

- move reviewed candidates into the canonical graph store

Inputs:

- normalized candidates
- entity matches
- evidence references
- review outcomes where required

Outputs:

- canonical nodes and event objects
- edges between them
- provenance links back to source documents

Rule:

- promotion must be idempotent
- promotion must retain provenance
- promotion must be reversible

### 10. Freshness / Drift Agent

Purpose:

- detect source breakage, stale content, and schema drift

Inputs:

- historical fetch metadata
- source registry
- expected cadence

Outputs:

- stale-source alerts
- drift warnings
- re-mapping tasks for broken sources

Examples:

- a city moved from one CMS to another
- a PDF title pattern changed
- a campaign portal altered its search flow

## Data Products Per Stage

Each stage should write its own artifact family.

### Source Registry

What it stores:

- source ID
- owner jurisdiction or institution
- source type
- URL pattern
- fetch strategy
- expected cadence

### Raw Store

What it stores:

- HTML
- JSON
- PDFs
- transcript files
- video metadata

### Extraction Store

What it stores:

- extracted text
- parsed sections
- detected tables
- candidate civic objects

### Candidate Store

What it stores:

- normalized but unpromoted objects
- evidence references
- confidence
- review status

### Canonical Store

What it stores:

- promoted graph objects
- stable IDs
- provenance references

## Queue Model

Use explicit queues rather than implicit script ordering.

Suggested queue families:

- `source_discovery_queue`
- `fetch_queue`
- `browser_fetch_queue`
- `extract_queue`
- `media_attribution_queue`
- `normalize_queue`
- `resolve_queue`
- `review_queue`
- `promote_queue`
- `freshness_queue`

Suggested queue item states:

- `pending`
- `claimed`
- `succeeded`
- `failed_retryable`
- `failed_terminal`
- `needs_review`
- `promoted`

## Review Boundaries

Human review should be required at these boundaries in v1:

- entity merges below high confidence
- speaker affiliation assignments with weak evidence
- inferred stance from ambiguous public comments
- vote extraction from messy minutes
- contract / grant recipient normalization when names are inconsistent
- article-quote identity resolution where the same person may be framed as a neutral resident but appears elsewhere as an activist, nonprofit staffer, board member, donor, or recurring advocate

## Source Strategy Matrix

### Meetings and Agenda Materials

Preferred approach:

- direct HTML / JSON / PDF fetch

Likely agents:

- Source Scout
- Surface Mapper
- Fetch
- Document Extract
- Normalization

### Campaign Finance

Preferred approach:

- direct portal fetch or exported filing pages

Likely agents:

- Source Scout
- Surface Mapper
- Fetch
- Document Extract
- Normalization
- Entity Resolution

### Disclosures

Preferred approach:

- official disclosure pages and attached PDFs

Likely agents:

- Fetch
- Document Extract
- Normalization

### Contracts / Grants

Preferred approach:

- procurement pages, agenda packets, board approvals, budget documents

Likely agents:

- Fetch
- Document Extract
- Normalization
- Entity Resolution

### Media

Preferred approach:

- RSS where available
- article fetch only for indexing and cross-reference

Likely agents:

- Fetch
- Document Extract
- Media Attribution
- Normalization

Important:

- media should enrich context, not outrank official documents
- local media quote extraction is still worth doing because it can surface recurring actors and mismatches between article framing and the broader public record

### Subscription Local Media

Preferred approach:

- operator-assisted access when a valid subscription exists
- save article metadata and stable citations even when full-text extraction is deferred

Examples:

- Marin Independent Journal archive access

Guardrails:

- do not assume full historical access without a logged-in session
- track whether a document was fully extracted, partially visible, or citation-only
- preserve article framing as article-scoped evidence, not canonical truth

## Suggested v1 Agent Stack

Start with a small stack.

### Must-Have

- Source Scout Agent
- Fetch Agent
- Document Extract Agent
- Media Attribution Agent
- Normalization Agent
- Entity Resolution Agent
- Promotion Agent

### Nice-to-Have Early

- Freshness / Drift Agent

### Defer Until Needed

- Browser Retrieval Agent
- heavy transcript processing
- automatic case-law ingestion

## Suggested v1 Execution Order

### Phase 1

Meetings and agenda packets for:

- Marin County Board of Supervisors
- San Rafael City Council

Objects to prove:

- Meeting
- AgendaItem
- Document
- Decision
- VoteCast

### Phase 2

San Rafael disclosures and Marin campaign finance.

Objects to prove:

- Actor
- MoneyFlow
- Document
- Membership

### Phase 3

San Rafael boards and commissions plus one county commission family.

Objects to prove:

- Institution
- Seat
- Appointment
- Meeting

### Phase 4

Contracts, grants, and recurring nonprofit/service-provider entities.

Objects to prove:

- MoneyFlow
- Actor
- Decision
- Issue

## What Should Not Be Agentic In v1

Do not make these autonomous at first:

- influence scoring
- moral labeling of organizations or officials
- automatic “astroturf” determination
- automatic outcome attribution
- automatic recurring-actor narratives

Those should be derived views built after the core event and evidence layers are reliable.

## Practical Recommendation

The first implementation should not start as “multi-agent AI.”

It should start as:

- a source registry
- deterministic fetchers
- document extraction workers
- a reviewable normalization layer
- a conservative entity-resolution layer

The agent framing is useful because it keeps responsibilities narrow.

But the runtime should stay boring wherever possible.
