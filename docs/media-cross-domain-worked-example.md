# Media Cross-Domain Worked Example

Verified: April 11, 2026

This note takes the media layer one step further.

The earlier examples proved:

- one article can produce `Mention -> Claim -> Actor`
- two articles can produce recurrence

This note proves the next step:

- recurring media actors and organizations can point into non-media graph objects without collapsing the evidence boundary

## Why There Are Two Different Examples

These are different join problems:

- `Mark Shotwell / Ritter Center`
  This is a person-to-organization-to-program-context join.

- `Downtown Streets Team`
  This is an organization-to-contract-to-moneyflow-to-decision join.

Treating them as the same pattern would be sloppy.

## Example 1: Mark Shotwell -> Ritter Center -> program context

What the repo already had:

- official submitted public comment from `Mark Shotwell`
- accepted affiliation claim to `Ritter Center`
- the September 20 Marin IJ article quoting `Mark Shotwell, chief executive officer of the Ritter Center`
- the official December 14, 2023 camping implementation plan naming `Ritter Center` as one of the City's nonprofit partners

What this lets us do:

- accept `actor-mark-shotwell -> actor-ritter-center`
- accept `actor-ritter-center -> record-san-rafael-camping-implementation-plan-2023-12-14`

What it does **not** let us do:

- invent a direct contract or campaign/disclosure join for Ritter Center just because the organization is present in the broader homelessness network

That is the right stop point for this evidence.

## Example 2: Downtown Streets Team -> contract -> money -> decision

What the repo already had:

- media mentions in both the August 24 and September 20 Marin IJ articles
- the official December 14, 2023 implementation-plan page naming Downtown Streets Team as a nonprofit partner
- the derived August 19 contract record for Downtown Streets Team
- the normalized `moneyflow-2024-08-19-dst-contract`
- the authorizing `decision-2024-08-19-resolution-15336`

What this lets us do:

- accept the media label as `actor-downtown-streets-team`
- link that actor to the official contract record
- link the contract record to the normalized money flow
- link the money flow to the authorizing decision

This is a full cross-domain chain:

`media -> org actor -> contract record -> moneyflow -> decision`

## Why This Matters

This is the first point where the media layer stops being self-contained.

It now points into:

- organization context
- program context
- contract records
- money flows
- decisions

That is the actual graph behavior the project needs.

## Boundary

The key rule is still the same:

- media can help identify and connect
- official records still carry the load-bearing downstream objects

So:

- `Mark Shotwell / Ritter Center` stops at organization and program context
- `Downtown Streets Team` keeps going because the repo already has the official contract and money chain

## Current Artifacts

- cross-domain example: [media-cross-domain-join-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/media-cross-domain-join-example-01.json)
- recurrence example: [marin-ij-recurrence-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/marin-ij-recurrence-example-01.json)
- first mention/claim example: [marin-ij-2024-08-24-mention-claim-example.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/marin-ij-2024-08-24-mention-claim-example.json)

## Next Move

The next useful step is no longer another local-media article.

It is one of:

- a recurring media actor that also appears in campaign or disclosure records
- a recurring media organization that also appears in grants or contracts outside case study 01
