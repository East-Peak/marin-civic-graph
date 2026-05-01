# Media Outside-Money Overlap Worked Example

Verified: April 12, 2026

This note adds the first direct overlap between the media layer and the outside-money layer.

It is still intentionally bounded.

The repo can now show that:

- a quoted local officeholder or councilmember also appears as the target of a public independent-expenditure filing
- the outside-spending committee, filing record, election, and seat can all join cleanly from public city-side evidence

The repo still cannot show, from this evidence alone:

- the filing amount
- the expenditure vendor chain
- any causal link between the later homelessness quote and the earlier outside-money filing

## Selected Examples

- `actor-kate-colin`
- `actor-rachel-kertz`

Outside-money source:

- public San Rafael `Independent Expenditure Filings 2020` folder
- public Form 496 filing rows exposed through the Laserfiche folder-listing service

Media sources:

- September 20, 2024 Marin IJ article for `Kate Colin`
- August 24, 2024 Marin IJ article for `Rachel Kertz`

## Why This Layer Works

This overlap is stronger than the first committee-continuity example because the filing titles themselves already preserve:

- spender committee name
- target candidate name
- support / oppose direction
- filing chronology

That is enough to accept:

- media mention -> canonical actor
- actor -> earlier candidacy
- outside committee -> Form 496 filing
- Form 496 filing -> supported target actor and target seat

It is not enough to accept:

- filing amount
- underlying donor schedule
- policy causation

## Accepted Links

- `mention-mij-2024-09-20-kate-colin -> actor-kate-colin`
- `actor-kate-colin -> candidacy-kate-colin-san-rafael-mayor-2020`
- `committee-sr-chamber-of-commerce-pac-2020-11-03-san-rafael-general-ie -> filing-san-rafael-ie-entry-32166`
- `filing-san-rafael-ie-entry-32166 -> actor-kate-colin`
- `mention-mij-2024-08-24-rachel-kertz -> actor-rachel-kertz`
- `actor-rachel-kertz -> candidacy-rachel-kertz-san-rafael-council-district-4-2020`
- `committee-whine-pac-2020-11-03-san-rafael-general-ie -> filing-san-rafael-ie-entry-32292`
- `filing-san-rafael-ie-entry-32292 -> actor-rachel-kertz`

## Methodology Result

The current public city-side campaign surface supports a real outside-money overlap layer even before raw filing PDFs are recoverable.

That gives the graph a defensible answer to a narrower question:

- which quoted local actors also had visible outside-spending support in the city-side filing surface

The project should still refuse to overclaim:

- how much was spent
- who ultimately funded the filing
- whether the later homelessness statements were driven by that campaign support

## Files

- [media-outside-money-overlap-example-01.json](/data/normalized/san-rafael-homelessness-01/media-outside-money-overlap-example-01.json)
- [bundle-01.json](/data/normalized/san-rafael-city-campaign-ie-01/bundle-01.json)
- [2026-04-12.json](/data/extracted/san-rafael-city-campaign-document-probe/2026-04-12.json)
