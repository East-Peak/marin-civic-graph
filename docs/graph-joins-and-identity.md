# Graph Joins And Identity

Date drafted: April 10, 2026

This document explains how the civic graph should be tied together.

The short version:

- raw files are not the graph
- front matter is not the join layer
- normalized objects carry stable IDs
- Neo4j materializes those IDs into nodes and edges
- identity resolution is a separate review step, not a side effect of parsing

## Design Goals

- keep joins explicit and rebuildable
- separate evidence from interpretation
- allow repeated reprocessing without changing canonical IDs casually
- support both machine extraction and human review
- make records, decisions, and actors joinable without flattening them

## Storage Layers

The join fabric starts before Neo4j.

```text
data/raw/         unchanged source captures
data/extracted/   parser output and record splits
data/normalized/  graph-ready candidate objects with stable IDs
Neo4j             materialized nodes and relationships
```

Each layer has a different job:

- `raw` preserves provenance
- `extracted` preserves parser output
- `normalized` defines the graph join keys
- Neo4j serves query and traversal

## What We Are Not Doing

We are not using Markdown front matter as the primary civic join mechanism.

Front matter is fine for:

- small curated reference notes
- human-edited source registries
- hand-maintained seed entities

It is not the right backbone for:

- thousands of meeting records
- repeated parser reruns
- machine-generated relationship sets
- partial identity matches

The durable join layer should be JSON or JSONL with explicit IDs.

## Join Types

There are four distinct join types in this project.

### 1. Structural Joins

These are the direct foreign-key style links that define process structure.

Examples:

- `meeting.institution_id`
- `agenda_item.meeting_id`
- `decision.meeting_id`
- `decision.agenda_item_id`
- `vote_cast.decision_id`
- `public_comment.agenda_item_id`

These should be deterministic and low-ambiguity.

### 2. Domain Joins

These tie process to actors, places, money, programs, and cases.

Examples:

- `committee.controlling_actor_id`
- `committee.treasurer_actor_id`
- `candidacy.candidate_actor_id`
- `candidacy.seat_id`
- `candidacy.election_id`
- `seat_service.actor_id`
- `seat_service.seat_id`
- `seat_service.election_id?`
- `filing.committee_id`
- `filing.filing_institution_id`
- `economic_interest_disclosure.filer_actor_id`
- `money_flow.to_actor_id`
- `money_flow.to_committee_id`
- `membership.actor_id`
- `appointment.seat_id`
- `decision.case_id`
- `procurement.program_id`
- `agreement.procurement_id`
- `agreement.counterparty_actor_id`
- `amendment.agreement_id`
- `deliverable.agreement_id`
- `performance_review.program_id`
- `application.project_id`
- `permit.project_id`
- `determination.application_id`
- `appeal.from_determination_id`
- `record.place_ids[]`
- `program.operator_actor_id`

These are often extracted from records but should still land as explicit ID references.

### 3. Provenance Joins

These connect graph facts back to source evidence.

Examples:

- `record.source_record_id`
- `record.artifact_paths[]`
- `claim.evidence[]`
- `record_segment.record_id`
- `mention.record_id`
- `decision.evidence_record_ids[]`

Without provenance joins, the graph becomes a pile of assertions.

### 4. Identity Joins

These connect raw names or mentions to canonical actors and institutions.

Examples:

- `mention.candidate_actor_ids[]`
- `claim.subject_actor_id`
- `public_comment.speaker_actor_id`
- `article_mention.quoted_actor_id`
- `membership.organization_actor_id`

These are the most error-prone joins, so they need their own review layer.

## ID Strategy

Every graph object should have one stable `id`.

The ID should:

- be ASCII
- be deterministic where possible
- encode the object type
- stay stable across re-extraction unless the underlying modeling decision changes

Examples already in the repo:

- `meeting-2024-08-19-san-rafael-city-council`
- `agenda-item-2024-08-19-5a`
- `decision-2024-08-19-resolution-15336`
- `record-2024-08-19-resolution-15336-text`
- `moneyflow-2024-08-19-defense-block-contract`
- `actor-downtown-streets-team`
- `case-boyd-v-city-of-san-rafael`

## ID Classes

### Canonical IDs

Use for durable browseable objects:

- `actor-*`
- `institution-*`
- `seat-*`
- `election-*`
- `committee-*`
- `place-*`
- `issue-*`
- `project-*`
- `program-*`
- `case-*`

These should change rarely.

### Process IDs

Use for things that happened:

- `meeting-*`
- `agenda-item-*`
- `decision-*`
- `candidacy-*`
- `filing-*`
- `disclosure-*`
- `application-*`
- `permit-*`
- `determination-*`
- `condition-*`
- `appeal-*`
- `procurement-*`
- `agreement-*`
- `amendment-*`
- `deliverable-*`
- `performance-review-*`
- `vote-*`
- `comment-*`
- `moneyflow-*`
- `proceeding-*`

These are usually anchored by date plus local context.

### Evidence IDs

Use for source-bearing objects:

- `record-*`
- `record-segment-*`

These often come from a source surface plus an extracted subdivision.

### Review IDs

Use for extracted-but-not-yet-promoted material:

- `mention-*`
- `claim-*`
- `lead-*`

These must be allowed to stay provisional.

## Source IDs Versus Graph IDs

Do not confuse `source_id` with graph object IDs.

Examples:

- `source_id = scotus-grants-pass-docket`
- `capture_id = scotus-grants-pass-docket__2026-04-10`
- `record_id = record-2024-06-28-grants-pass-majority-opinion`
- `case_id = case-city-of-grants-pass-v-johnson`

The source surface is where we discovered the artifact.
The record ID is the graph object for the actual artifact.

## Artifact Supersession

Proxy-to-direct upgrades should not break graph identity.

Rules:

- keep `source_id` stable when the source surface is the same
- create a new `capture_id` for each improved fetch
- keep the same `record_id` when the newer artifact is the same semantic record
- update normalized artifact references to the higher-fidelity capture only after review
- keep the older proxy capture in `data/raw/` for provenance

This means:

- proxy text -> direct PDF is usually a provenance upgrade
- proxy page -> exact child attachment may require new child `record-*` nodes

The key test is not file format. The key test is object identity.

## Normalized File Shape

Normalized files should not depend on path-based inference.

They should contain explicit IDs and explicit references.

Example pattern:

```json
{
  "id": "record-2024-08-19-resolution-15336-text",
  "record_class": "legislative_record",
  "meeting_id": "meeting-2024-08-19-san-rafael-city-council",
  "agenda_item_id": "agenda-item-2024-08-19-5a",
  "decision_ids": [
    "decision-2024-08-19-resolution-15336"
  ],
  "related_moneyflow_ids": [
    "moneyflow-2024-08-19-defense-block-contract"
  ],
  "source_record_id": "doc-2024-08-19-item-5a-report",
  "artifact_paths": [
    "data/raw/san-rafael-aug-19-2024-council-meeting/2026-04-10/item-5a-report.pdf"
  ],
  "text_path": "data/extracted/san-rafael-aug-19-2024-council-meeting/item-5a-resolution-15336.txt"
}
```

The importer should never have to guess the join keys from filenames.

If a normalized object uses a single `artifact_path`, that path should point to the current preferred artifact for that record.

Older captures remain discoverable through:

- the same `source_id`
- prior raw capture directories
- raw `manifest.json` files

## Neo4j Materialization

The graph database should be rebuildable from normalized files.

Importer rules:

- `MERGE` nodes by `(label, id)`
- set immutable fields on first insert
- update derived fields on rerun
- `MERGE` relationships by source ID plus target ID plus relationship type
- never rely on internal Neo4j node IDs

That means the real source of truth is file-backed normalized data, not hand-edited graph state.

## Identity Resolution

Identity resolution should be explicit, reviewable, and reversible.

### Raw Name

This is whatever the source says.

Examples:

- `Kate`
- `Katie Rice`
- `Mark Shotwell, Ritter Center`
- `Mill Valley resident John Doe`

### Mention

A mention is a source-bounded extracted reference.

Fields might include:

- `mention_text`
- `record_id`
- `record_segment_id?`
- `name_raw`
- `role_raw?`
- `organization_raw?`
- `candidate_actor_ids[]`
- `confidence`

### Claim

A claim is a reviewable assertion derived from one or more mentions or records.

Examples:

- this quoted speaker is probably `actor-mark-shotwell`
- this article framed the actor as a resident
- the record implies this contract recipient is `actor-wehope`

Claims can be accepted, rejected, or left unresolved.

### Canonical Promotion

A join is promoted into the canonical graph only when the evidence is good enough.

Examples:

- `public_comment.speaker_actor_id = actor-mark-shotwell`
- `membership.actor_id = actor-mark-shotwell`
- `membership.organization_actor_id = actor-ritter-center`

This is how we avoid turning weak article framing into permanent graph truth.

## Worked Example: August 19 Meeting Chain

This is the current live example in the repo.

Process chain:

- `meeting-2024-08-19-san-rafael-city-council`
- `agenda-item-2024-08-19-5a`
- `decision-2024-08-19-ordinance-2040-introduction`
- `decision-2024-08-19-resolution-15336`

Evidence chain:

- `doc-2024-08-19-item-5a-report`
- `record-2024-08-19-ordinance-2040-text`
- `record-2024-08-19-resolution-15336-text`
- `record-2024-08-19-contract-defense-block-security`
- `record-2024-08-19-contract-wehope`

Domain chain:

- `moneyflow-2024-08-19-defense-block-contract`
- `moneyflow-2024-08-19-wehope-contract`
- `actor-defense-block-security`
- `actor-wehope`
- `place-mahon-creek-path`

The important point is that no one object carries the whole truth.

The resolution record does not replace the decision.
The contract record does not replace the money flow.
The actor node does not replace the record evidence.

The joins tie them together.

## Worked Example: Media Record Versus Actor Identity

Suppose a Marin IJ article quotes a person as a `Mill Valley resident`.

We should model that as:

- `record-*` for the article
- `mention-*` for the quoted name and role label
- `claim-*` for any candidate affiliation inference

Only later, if corroborated by meetings, organization rosters, filings, or other official records, do we promote:

- `actor-*`
- `membership-*`
- `public_comment.speaker_actor_id`

Article framing is evidence.
It is not automatic identity truth.

## What Lives Outside The Graph

These should stay file-backed, not node-backed by default:

- full HTML
- full PDF text blobs
- OCR debug output
- parser logs
- low-signal token matches

The graph should point to them, not absorb them wholesale.

## What This Enables Next

Once the join rules are stable, the same graph can absorb new domains without changing the core architecture.

The next obvious expansion surfaces are:

- permits, applications, denials, and appeals
- code-enforcement notices and abatement actions
- procurement and vendor performance records
- grand jury reports, findings, and agency responses
- court orders, injunctions, and appellate opinions
- property and land-use records

The point is not to build a separate graph for each domain.
The point is to make them all legible through the same ID and provenance discipline.
