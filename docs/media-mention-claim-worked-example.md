# Media Mention And Claim Worked Example

Verified: April 11, 2026

This note shows the first real `Record -> Mention -> Claim -> Actor` media pass in the repo.

The goal is not to solve the whole media layer. The goal is to prove that the graph can:

- upgrade one Marin IJ article from citation-only to article-body extraction
- preserve article framing exactly as printed
- promote only the joins that are strong enough
- leave ambiguous named people in the review layer

## Selected Record

- article: `San Rafael to establish camp for homeless people along Mahon Creek`
- Marin Independent Journal
- published: `2024-08-24T18:20:03Z`
- canonical record ID: `record-mij-2024-08-24-establish-camp-mahon-creek`

## Why This Article

This one record gives all three outcomes the project needs to support:

- one known official already canonical in the graph
- one named local speaker already present in the case-study evidence
- two named people who should stay unresolved

That makes it a good pressure test for the review boundary.

## Capture Path

The raw article body was captured through the public WordPress post API, not through browser scraping:

- raw capture: [manifest.json](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-ij-2024-08-24-mahon-creek-article/2026-04-11/manifest.json)
- raw response: [response.json](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-ij-2024-08-24-mahon-creek-article/2026-04-11/response.json)
- extracted layer: [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/marin-ij-2024-08-24-mahon-creek-article/2026-04-11.json)
- normalized worked example: [marin-ij-2024-08-24-mention-claim-example.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/marin-ij-2024-08-24-mention-claim-example.json)

This matters because it answers the old methodology question directly: at least some Marin IJ records can graduate from citation-only without operator login.

## Outcomes

### 1. Canonical official join: Rachel Kertz

The article prints:

- `Councilmember Rachel Kertz`

Why this is safe:

- full name is printed
- official role label is printed
- the same actor is already canonical in the San Rafael seed layer

Result:

- promote the Mention to `actor-rachel-kertz`

### 2. Case-scoped join: Katie Fleet

The article prints:

- `Katie Fleet, who lives in the Gerstle Park neighborhood`

The repo already had:

- an official submitted-correspondence record for `Katie Fleet`
- the same issue thread
- the same school-community concern around Parkside

Result:

- accept a case-scoped join to `actor-katie-fleet`
- do not promote her into the citywide canonical seed layer yet

This is the useful middle case. The actor is strong enough for the case study, but not yet strong enough to become a durable citywide identity seed.

### 3. Hold for review: Kevin Bruner

The article prints:

- `Kevin Bruner, also a parent to a child at the children's center`

What the repo has beyond the article:

- nothing strong enough yet

Result:

- keep the Mention
- do not create or promote a stronger actor join yet

### 4. Hold for review: Mark Rivera

The article prints:

- `Mark Rivera, an unhoused resident of San Rafael`

What the repo has beyond the article:

- no corroborating identity source yet

Result:

- keep the Mention
- do not promote anything beyond article-scoped framing

### 5. Case-scoped official join: John Stefanski

The article prints:

- `John Stefanski, assistant city manager`

The repo already had:

- official San Rafael records naming John Stefanski in the same homelessness thread

Result:

- accept a case-scoped actor join to `actor-john-stefanski`

## Why This Matters

This worked example proves three things:

- citation-only Marin IJ records can graduate when the article body is reproducibly accessible
- one article can legitimately contain promoted joins and unresolved mentions at the same time
- article framing and broader graph truth can stay separate without making the system useless

## What This Does Not Prove

- that every Marin IJ article is open through the same path
- that article-only residents should be promoted automatically
- that quote extraction alone is enough to infer advocacy or NGO affiliation

## Next Move

The next useful media step is not a bigger parser. It is a second article on the same thread that tests recurrence:

- same quoted person across multiple articles
- same person across article and public comment
- same person across article and organization or disclosure record
