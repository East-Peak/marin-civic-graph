# Media Disclosure Overlap Worked Example

Verified: April 11, 2026

This note adds the first direct overlap between the media layer and the disclosure layer.

It does **not** claim that the article and the disclosure are substantively about the same transaction.

It proves something narrower and more useful:

- the same canonical officeholder can appear in local media and in local disclosure records
- the graph can connect those records through actor identity plus seat / seat-service structure

## Selected Example

- media record: `record-mij-2024-09-20-prepares-site-authorized-camp`
- disclosure filing: `filing-2025-09-04-kate-colin-form-803`
- shared actor: `actor-kate-colin`

## Why This One Works

The September 20 Marin IJ article explicitly prints:

- `San Rafael Mayor Kate Colin`

The repo already had:

- canonical `actor-kate-colin`
- mayor seat and `SeatService`
- the official local Kate Colin Form 803 filing
- the normalized behested-payment money flow from that filing

That makes this a clean overlap.

## What The Join Actually Is

The accepted chain is:

`media mention -> actor-kate-colin -> seatservice-kate-colin-mayor-current -> filing-2025-09-04-kate-colin-form-803 -> moneyflow-2025-08-08-pge-to-canal-alliance-form-803`

That is an identity-and-office continuity join.

## What It Is Not

It is **not**:

- evidence that the quoted homelessness statement caused the later behested payment
- evidence that the payment was about the Mahon Creek program
- evidence of corruption or hidden influence

That would require separate evidence. This example is about graph structure, not accusation.

## Why This Matters

This is the first point where the media layer can point into:

- official local disclosure filings
- office/seat structure
- normalized money flows outside the meeting/contract layer

That gives the graph a real bridge between public narrative and public filing data.

## Current Artifact

- overlap example: [media-disclosure-overlap-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/media-disclosure-overlap-example-01.json)

## Current Boundary

This is a disclosure overlap, not a campaign overlap.

The repo does not yet have a similarly clean example where the same recurring media actor or organization also appears in a campaign-finance filing on this thread.

## Next Move

The next stronger finance-side test would be:

- a recurring media actor or organization that also appears in a campaign committee, contribution, independent-expenditure, or Form 700 thread
