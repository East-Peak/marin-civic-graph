# Spec Review Prompt for Codex

## Context

You built the original Marin Civic Graph — the raw captures, the normalized bundles, the 28-type schema, the projection pipeline, the query pack, and the read-model layer. That work is real and valuable.

We're now productionizing it. Claude (Opus) and Stuart designed a v1 spec that restructures the project into a Neo4j-backed investigation and transparency tool with a Next.js frontend, graph visualizations, a data explorer, and an AI chat interface powered by Claude API.

The spec is at `docs/specs/2026-04-14-marin-civic-graph-v1-design.md`. Read it completely before responding.

## What happened during the design process

1. Claude proposed collapsing the schema from 28 types to 13. Stuart asked for a stress test.
2. You reviewed it and argued convincingly that 13 was too collapsed — SeatService, Candidacy, Agreement, Amendment, Proceeding, Place, and Issue should be restored as nodes.
3. Claude accepted most of your arguments, pushed back on CaseParticipation (too few instances to justify a node) and ValidationCheck (pipeline QA, not civic entity).
4. You accepted those pushbacks but argued Program should stay (sanctioned camping, camping ordinance implementation, Building Forward are not projects or organizations). Claude agreed.
5. Final schema: 21 core types + ValidationCheck in a QA lane + PublicComment and BallotMeasure deferred.

The schema is settled. This review is about everything else in the spec.

## Your task

Review the spec as an adversarial collaborator. You know this data and this domain better than anyone — you built the source adapters, you understand the quirks of Laserfiche and NetFile and Granicus, you know where the data is clean and where it's messy. Use that knowledge.

### 1. Ingestion reality check

The spec says v1 uses a "one-time bulk import" that reads existing `data/raw/` and `data/normalized/` and loads into Neo4j.

- Is this actually straightforward? What are the hard parts?
- The normalized bundles already have the node/edge structure. Can you go normalized → Neo4j directly, or is there meaningful transformation work?
- What data quality issues will surface during import that the spec doesn't account for? (Duplicate actors, missing references, malformed dates, OCR errors, etc.)
- The spec says "no intermediate normalized bundles" for v2 ingestion. You built the bundles for a reason. What breaks if you skip them?

### 2. Neo4j AuraDB fit

- The current graph is ~6K nodes / ~21K edges. What's the realistic ceiling for all of Marin County (all cities, all record types, multi-year)?
- Are there any Cypher query patterns needed for the 6 investigation use cases that are expensive or awkward in Neo4j?
- The spec proposes writing ingestion directly to AuraDB over the network from the Mac mini. Any concerns about bulk write performance, transaction size, or AuraDB rate limits?
- Is there anything in the current data model that doesn't map cleanly to Neo4j's property graph model?

### 3. Product surface gaps

- The spec describes 5 visualization types (radial, Sankey, timeline, org tree, network explorer). Given the actual data in the graph, which of these will look compelling vs. sparse?
- The data explorer proposes "predefined query templates." Based on what you know about the data, what are the 5-10 most useful predefined queries?
- The AI chat's "investigation mode" assumes users build a saved collection of entities. Is there a simpler entry point for investigation that the spec misses?
- Entity pages for all 21 node types — which types will have rich, interesting pages and which will be thin stubs at current data volume?

### 4. Technical risks

- What's the hardest thing to build in this spec?
- What's most likely to go wrong?
- Is there anything the spec assumes is easy that's actually hard?
- Are there dependencies between components that could block progress?

### 5. What the spec gets wrong

- Anything factually incorrect about the existing data, its structure, or its quality?
- Anything that contradicts decisions already made and documented in the repo?
- Anything that would force re-doing work that's already been done correctly?

### 6. What the spec is missing

- Any critical feature or capability that's absent?
- Any operational concern (backups, data refresh, monitoring) not addressed?
- Any security consideration for an invite-only tool that handles public records?

Be specific. Reference actual files, actual data shapes, actual source quirks from the repo. Don't rubber-stamp and don't nitpick — focus on things that would actually cause problems during implementation.
