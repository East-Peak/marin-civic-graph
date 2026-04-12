# Legal Precedent 02

`legal-precedent-02` is the second normalized legal bundle.

It widens the legal lane from one local case to one local case plus one controlling Supreme Court precedent:

- local constraint bundle: `Boyd v. City of San Rafael`
- external controlling precedent bundle: `City of Grants Pass v. Johnson`

## What It Contains

- the official Supreme Court docket page for `23-175`
- the official June 28, 2024 Supreme Court slip opinion PDF
- the official San Francisco City Attorney amicus-announcement post
- crosswalk references to San Rafael's June 28 statement and September 2 explainer
- first normalized external-precedent objects:
  - `Case`
  - `Proceeding`
  - `CaseParticipation`
  - `crosswalk` back into San Rafael's August 19, 2024 response chain

## Why This Bundle Matters

This is the first legal bundle that cleanly separates:

- the controlling national precedent record
- institutional response / advocacy records
- the local San Rafael implementation response

That distinction matters. `Grants Pass` is precedent. San Rafael's statement and explainer are not precedent; they are local interpretations and response records.

## Current Boundary

This bundle is strong enough to support:

- official case identity
- petition / cert / argument / opinion proceedings
- petitioner / respondent / amicus participation
- crosswalks into San Rafael's legal posture and decision chain

It does **not** yet include:

- the lower-court district and Ninth Circuit orders that the Supreme Court reversed and remanded
- a direct capture of the San Francisco amicus brief PDF itself
- graph-v1 import scope changes in the same step

## Primary Artifacts

- [Grants Pass legal bundle](../data/normalized/legal-precedent-02/bundle-01.json)
- [Supreme Court docket extract](../data/extracted/scotus-grants-pass-docket/2026-04-12.json)
- [Supreme Court opinion extract](../data/extracted/scotus-grants-pass-opinion/2026-04-12.json)
- [Supreme Court opinion text](../data/extracted/scotus-grants-pass-opinion/opinion.txt)
