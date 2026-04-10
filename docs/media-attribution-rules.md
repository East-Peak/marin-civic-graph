# Media Attribution Rules

Date drafted: April 10, 2026

This document defines how local-media quotes and affiliations should be handled.

It exists to solve one recurring problem:

- local articles often quote people as residents, neighbors, advocates, or volunteers
- the same people may recur elsewhere as activists, nonprofit staff, board members, donors, or regular public commenters

The project needs to preserve article framing without laundering it into canonical truth.

## Core Principle

Store two separate things:

1. what the article said
2. what the broader public record supports

Do not silently collapse them.

## Objects Involved

- `Record` with `record_class = media_record`
- `ArticleMention`
- `Actor`
- `Claim`

## What Counts As An Article-Scoped Fact

These can be stored directly on `ArticleMention`:

- raw name as printed
- exact role label as printed
- exact affiliation label as printed
- quote excerpt
- whether the article explicitly described the person as resident / advocate / neighbor / official / spokesperson

Examples:

- "Mill Valley resident"
- "homeless advocate"
- "executive director of X"
- "neighboring business owner"

These are article facts, not global truths.

## What Counts As A Cross-Source Claim

These require corroboration outside the article unless the article itself is explicit and authoritative:

- person is affiliated with organization X
- person is a recurring activist on issue Y
- person has board role Z
- person was presented as neutral but is in fact connected to advocacy network Q

## Confidence Levels

### Level 1: Article-only

Meaning:

- the article prints a name and role label
- no external corroboration yet

Allowed actions:

- create `ArticleMention`
- create unresolved actor candidate if needed

Not allowed:

- promote canonical organization membership

### Level 2: Explicit article affiliation

Meaning:

- the article explicitly states an affiliation

Allowed actions:

- store article-scoped affiliation
- create a candidate claim for canonical affiliation

Not allowed by default:

- auto-promote a long-term membership without corroboration unless the source is especially strong

### Level 3: Corroborated affiliation

Meaning:

- article mention plus external corroboration from one or more stronger sources

Examples of corroboration:

- organization website
- board roster
- meeting minutes
- public comment self-identification
- campaign filing
- Form 700 or Form 990

Allowed actions:

- promote canonical membership or affiliation claim

### Level 4: Recurring actor pattern

Meaning:

- actor appears across multiple sources and event types

Examples:

- quoted in article
- appears in public comments
- sits on board
- receives grant-funded role
- donates to aligned candidates

Allowed actions:

- generate derived views and recurrence summaries

Not allowed:

- moralized labels like "astroturf" without separate evidence

## Review Rubric

For each quoted person, reviewers should ask:

1. Is the person uniquely identifiable?
2. What exact role did the article assign?
3. Did the article explicitly disclose any affiliation?
4. Does the person appear elsewhere in the graph?
5. Is there corroboration for a broader affiliation claim?
6. Is the broader claim strong enough to promote, or does it stay as a lead?

## Allowed Promotion Rules

### Safe To Promote

- article explicitly identifies someone as executive director / staff / board member, and that role is corroborated elsewhere
- article quote matches a known public official already in the graph
- article quote matches a known recurring public commenter with strong ID confidence

### Hold For Review

- common-name resident quotes
- vague labels like "advocate" or "volunteer"
- article-only implication of organizational role
- suspected activist identity inferred from style or tone alone

### Do Not Promote

- "seems coordinated"
- "probably NGO-backed"
- "sounds like same guy"
- any accusation derived from intuition rather than evidence

## Useful Derived Views

These are valid outputs once the evidence is there:

- quoted as resident, elsewhere identified as nonprofit staff
- quoted as neighbor, elsewhere recurring public commenter on same issue
- quoted without disclosed affiliation, affiliation visible in stronger public records
- article disclosed affiliation clearly

## Dangerous Derived Views

These should be avoided or heavily qualified:

- fake resident
- paid protester
- astroturf actor
- in cahoots

Those may be hypotheses or user interpretations, but they are not safe graph labels.

## Source Ranking For Attribution Work

Highest confidence:

- official rosters
- filings
- signed disclosures
- self-identified public comment records

Medium confidence:

- organization website bios
- local media explicit identifications

Lower confidence:

- social media
- anecdotal user reports
- indirect mention chains

## Marin IJ Note

For Marin IJ and similar local outlets:

- treat quote extraction as high value
- treat affiliation resolution as medium-to-high review risk
- preserve article framing verbatim
- support a citation-only mode when title / URL / date are known but article-body extraction is deferred
- do not rely on subscription-local-media quotes alone to establish a canonical political role
