# Identity Resolution Submodel

Date drafted: April 11, 2026

This note defines how recurring people and organizations should become stable graph objects.

The goal is not to make identity resolution invisible. The goal is to make it explicit, evidence-backed, and reversible.

## Why This Layer Exists

The repo now has the same actors showing up across:

- meeting packets
- public comments
- contracts
- procurement records
- campaign filings
- Form 700 / Form 803 disclosures
- city updates and releases

Without a canonical identity layer, those records stay useful in isolation but weak in combination.

## Core Rule

Identity is not a side effect of parsing.

The pipeline is:

1. observed label
2. `Mention`
3. `Claim`
4. canonical seed
5. promoted join in process objects

This is the same evidence discipline already used elsewhere in the project:

- `Record` preserves the artifact
- `Mention` preserves the source-bounded reference
- `Claim` preserves the reviewable assertion
- canonical seed objects stabilize later joins

## Identity States

### Observed Label

This is exactly what one source says.

Examples:

- `Mayor Kate Colin`
- `Kate Colin`
- `Defense Block Security (DBS)`
- `DST`

Observed labels should be stored, not normalized away.

### Mention

A `Mention` is a bounded appearance inside one record or record segment.

Typical fields:

- `record_id`
- `segment_id?`
- `name_raw`
- `role_label?`
- `affiliation_label?`
- `candidate_actor_ids[]`
- `confidence`

### Claim

A `Claim` is the review layer between raw labels and durable graph truth.

Identity-focused claim types include:

- `actor_role_at_institution`
- `actor_affiliation`
- `alias_resolution`
- `raw_seed_resolution`

Claims can be accepted, rejected, or left unresolved.

### Canonical Seed

A canonical seed is a file-backed actor or institution candidate that is strong enough to reuse across slices.

The seed layer is where the project stops saying:

- `actor-mayor-kate`
- `actor-councilmember-bushey`

and starts saying:

- `actor-kate-colin`
- `actor-maribeth-bushey`

without pretending that every related seat, term, or district boundary is already solved.

## Promotion Standards

### Promote Directly

Promote when the identity is explicit in official records and there is little ambiguity.

Good examples:

- a full person name plus office label in an official meeting packet
- a signed official filing naming the filer
- a contract exhibit naming the counterparty
- a nonprofit named explicitly in both a contract and a city update

### Promote With Alias Capture

Promote the canonical actor, but preserve alternate labels.

Examples:

- `Defense Block Security` plus `DBS`
- `Downtown Streets Team` plus `DST`
- `Mayor Kate Colin` plus `Kate Colin`

### Hold In Claim Layer

Do not promote when the evidence only supports a hypothesis.

Examples:

- common-name person with no corroborating institution or filing context
- acronym-only org label with no explicit expansion
- media-framed “resident” identity with no corroborating official record
- inferred seat or district assignment from a meeting packet alone

## What A Seed Bundle Should Contain

The canonical seed bundle should be normalized JSON, not front matter.

It should contain:

- `record_refs`
- `institution_candidates`
- `actor_candidates`
- `claim_candidates`
- `methodology_findings`
- `promotion_constraints`
- `open_questions`

Useful actor fields:

- `id`
- `name`
- `actor_type`
- `seed_status`
- `observed_labels[]`
- `aliases[]`
- `evidence_record_ids[]`
- `resolves_raw_actor_seed_ids[]`
- `notes`

Useful claim fields:

- `id`
- `claim_type`
- `status`
- `confidence`
- `subject_actor_id`
- `institution_id?`
- `organization_actor_id?`
- `role_label?`
- `effective_date?`
- `evidence_record_ids[]`

## First Identity Slice

The first live identity seed bundle is:

- [canonical-seeds-san-rafael-01.json](/data/normalized/canonical-seeds-san-rafael-01.json)

It does three bounded things:

- resolves the August 19, 2024 San Rafael council roster into canonical people
- stabilizes a first group of recurring organizations across homelessness, procurement, and disclosure slices
- records role claims without overpromoting term boundaries
- seeds explicit San Rafael council seats and current `SeatService` objects from stronger official city pages

## What This Layer Does Not Do

- it does not infer current officeholders from older records
- it does not silently merge organizations because names feel similar
- it does not backfill election or district structure from weak clues
- it does not treat media framing as identity truth

## Immediate Use

This layer is mainly for:

- joining the August 19 homelessness bundle to the Form 803 slice
- replacing raw actor labels in earlier normalized files with canonical actor IDs over time
- giving future Marin IJ `Mention -> Claim` work a stable actor set to resolve against
