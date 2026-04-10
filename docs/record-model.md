# Record Model

Date drafted: April 10, 2026

This document defines how `Record` should behave in the graph.

The goal is to make records first-class objects rather than leaving them as blobs attached to meetings or decisions.

## Core Distinction

Three concepts need to stay separate:

- `Record`
- `Event`
- `Decision`

### Record

A persistent source artifact.

Examples:

- Marin IJ article
- ordinance text
- resolution text
- staff report
- packet
- minutes
- contract exhibit
- campaign filing

### Event

A thing that happened in time.

Examples:

- city council meeting
- public hearing
- lawsuit filing
- camp opening

### Decision

A formal outcome or action.

Examples:

- ordinance introduction
- resolution adoption
- contract authorization
- appropriation
- enforcement change

Rule of thumb:

- ordinance PDF = `Record`
- August 19 meeting = `Event`
- adoption of Resolution 15336 = `Decision`

## Why This Matters

Many civic questions are actually record questions:

- which record introduced the proposal?
- which record authorized the action?
- which record memorialized the vote?
- which record reported the public framing?
- which records duplicate each other?

If records are just attachments, those questions stay hard.

## Record Classes

Suggested first-pass classes:

- `meeting_record`
- `legislative_record`
- `media_record`
- `financial_record`
- `contract_record`
- `legal_record`
- `program_record`

Examples:

- agenda / packet / minutes / video page = `meeting_record`
- ordinance / resolution = `legislative_record`
- Marin IJ article = `media_record`
- Form 460 / 700 / 803 / 990 = `financial_record`
- contract exhibit / PSA = `contract_record`
- court order / complaint / amicus post = `legal_record`
- sanctioned camping FAQ / implementation page = `program_record`

## Core Record Fields

- `id`
- `record_class`
- `record_type`
- `title`
- `source_url`
- `publisher`
- `published_at`
- `source_tier`
- `artifact_paths[]`
- `text_path?`
- `duplicate_of_record_id?`
- `supersedes_record_id?`

Useful optional fields:

- `meeting_id?`
- `agenda_item_id?`
- `decision_id?`
- `issue_ids[]`
- `place_ids[]`
- `actor_ids[]`

## Core Relationships

These are the relationships worth standardizing early.

### Record To Decision

- `record_introduces_decision`
- `record_memorializes_decision`
- `record_authorizes_decision`
- `record_implements_decision`
- `record_reports_on_decision`

Examples:

- staff report `record_introduces_decision` ordinance introduction
- minutes `record_memorializes_decision` resolution adoption
- Marin IJ article `record_reports_on_decision` authorized camp approval

### Record To Record

- `record_attached_to_record`
- `record_cites_record`
- `record_duplicates_record`
- `record_supersedes_record`
- `record_extracts_from_record`

Examples:

- contract exhibit `record_attached_to_record` resolution
- FAQ page `record_cites_record` ordinance
- staff-report landing-page PDF `record_duplicates_record` item-5a-report PDF

### Record To Event

- `record_for_event`
- `record_reports_on_event`

Examples:

- agenda `record_for_event` August 19 council meeting
- IJ article `record_reports_on_event` August 19 council hearing

### Record To Actor / Place / Issue

- `record_quotes_actor`
- `record_mentions_actor`
- `record_about_place`
- `record_about_issue`

Examples:

- IJ article `record_quotes_actor` person once quote extraction exists
- implementation page `record_about_place` Mahon Creek Path
- ordinance text `record_about_issue` camping ordinance

## Worked Examples

### 1. August 19, 2024 Item 5.a

Minimal chain:

- `meeting-2024-08-19-san-rafael-city-council`
- `agenda-item-2024-08-19-5a`
- `record: item-5a-report.pdf`
- `decision: ordinance-2040-introduction`
- `decision: resolution-15336-adoption`
- `record: minutes.pdf`

Relationships:

- item-5a report `record_introduces_decision` ordinance introduction
- item-5a report `record_introduces_decision` resolution 15336
- minutes `record_memorializes_decision` ordinance introduction
- minutes `record_memorializes_decision` resolution adoption

### 2. Duplicate Record Example

From the first bundle:

- `item-5a-report.pdf`
- `staff-report.pdf`

These have the same SHA-256 and should not become two independent canonical records with separate truth.

Relationships:

- landing-page staff report `record_duplicates_record` item-5a report

### 3. Resolution Exhibit Splitting

Current state:

- one dense record contains resolution text plus exhibits

Desired state:

- `resolution-15336`
- `contract-defense-block`
- `contract-other-junk`
- `contract-wehope`
- `contract-downtown-streets-team`

Relationships:

- each contract `record_attached_to_record` resolution 15336
- each contract `record_authorizes_decision` or links through the same decision chain

### 4. Marin IJ Citation Layer

Current state:

- citation-only `media_record`
- title
- URL
- published date
- coarse phase

Future state:

- raw article HTML snapshot
- extracted text
- quote blocks
- `ArticleMention` candidates

Relationships:

- IJ article `record_reports_on_decision` resolution 15336 or the sanctioned camp rollout
- once extracted, article `record_quotes_actor` quoted speakers

## Promotion Path

The project should allow records to mature in stages.

1. `citation_only`
   Title, URL, date, publisher

2. `raw_capture`
   HTML, PDF, or snapshot stored in `data/raw`

3. `text_extraction`
   Clean text and machine-readable metadata in `data/extracted`

4. `record_normalization`
   Canonical `Record` node candidate in `data/normalized`

5. `claim_promotion`
   Quotes, affiliations, decisions, money flows, or memberships promoted only after review

## Immediate Design Implications

Three near-term changes follow from this model:

- split ordinances and resolutions out of packets into their own `Record` nodes
- split exhibits and attachments into child records where they matter operationally
- keep media at citation-only until article-body extraction is reliable

## Recommended Next Step

Use the August 19 packet as the first record-splitting exercise:

1. extract ordinance 2040 as a `legislative_record`
2. extract resolution 15336 as a `legislative_record`
3. extract each exhibit contract as a `contract_record`
4. link them back to the meeting, agenda item, and decisions
