# Media-Campaign Overlap Worked Example

Verified: April 12, 2026

This note records the first direct media-to-campaign overlap in the repo.

The goal is narrow:

- prove that one quoted media actor can join cleanly into a real city-side campaign committee
- preserve the boundary between identity continuity and causal claims about policy influence

## Example

Chosen actor:

- `Rachel Kertz`

Media source:

- August 24, 2024 Marin IJ article on the Mahon Creek sanctioned-camp decision

Campaign source:

- public San Rafael city-side campaign folder `Rachel Kertz for San Rafael City Council 2024`
- public filing rows exposed through the Laserfiche folder-listing service

## Why This One Works

This overlap is strong because:

- the media article prints the full name and official role
- the actor is already canonical in the San Rafael identity seed bundle
- the city-side campaign layer now exposes a committee title, filing rows, and stable entry ids for the same actor

That is enough to accept:

- media mention -> canonical actor
- actor -> candidate committee
- committee -> candidacy
- committee -> filing rows

It is not enough to accept:

- article quote -> campaign money motive
- campaign filing -> proof of policy causation

## Accepted Links

- `mention-mij-2024-08-24-rachel-kertz -> actor-rachel-kertz`
- `actor-rachel-kertz -> committee-rachel-kertz-for-san-rafael-city-council-2024`
- `committee-rachel-kertz-for-san-rafael-city-council-2024 -> candidacy-rachel-kertz-san-rafael-council-district-4-2024`
- `committee-rachel-kertz-for-san-rafael-city-council-2024 -> filing-san-rafael-campaign-entry-37365`
- `committee-rachel-kertz-for-san-rafael-city-council-2024 -> filing-san-rafael-campaign-entry-37653`

Representative filing rows:

- `Form 460 - Rachel Kertz for City Council 2024; 06-30-24`
- `Form 497 - Rachel Kertz for City Council 2024; 09-19-24`

## Methodology Result

The important takeaway is that the campaign overlap is now real, but still bounded.

The graph can now answer:

- this quoted actor also had an active campaign committee and public filing trail in the same election cycle

The graph should still refuse to answer, without more evidence:

- this specific homelessness quote was financially driven
- this filing proves campaign influence on the Mahon Creek decision

## Files

- [media-campaign-overlap-example-01.json](/data/normalized/san-rafael-homelessness-01/media-campaign-overlap-example-01.json)
- [bundle-01.json](/data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json)
- [marin-ij-2024-08-24-mention-claim-example.json](/data/normalized/san-rafael-homelessness-01/marin-ij-2024-08-24-mention-claim-example.json)
