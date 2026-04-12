# Legal Precedent 02

`legal-precedent-02` is the second normalized legal bundle.

It widens the legal lane from one local case to one local case plus one controlling Supreme Court precedent:

- local constraint bundle: `Boyd v. City of San Rafael`
- external controlling precedent bundle: `City of Grants Pass v. Johnson`

## What It Contains

- the District of Oregon July 22, 2020 opinion and order
- the District of Oregon August 26, 2020 judgment
- the official Ninth Circuit July 5, 2023 order and amended opinion
- the official Supreme Court docket page for `23-175`
- the official June 28, 2024 Supreme Court slip opinion PDF
- the official San Francisco City Attorney amicus-announcement post
- crosswalk references to San Rafael's June 28 statement and September 2 explainer
- first normalized external-precedent objects:
  - `Case`
  - `Proceeding`
  - `CaseParticipation`
  - district / appellate / Supreme Court case-lineage crosswalk
  - `crosswalk` back into San Rafael's August 19, 2024 response chain

## Why This Bundle Matters

This is the first legal bundle that cleanly separates:

- the lower-court district and appellate chain
- the controlling national precedent record
- institutional response / advocacy records
- the local San Rafael implementation response

That distinction matters. `Grants Pass` is precedent. San Rafael's statement and explainer are not precedent; they are local interpretations and response records.

## Current Boundary

This bundle is strong enough to support:

- district, appellate, and Supreme Court case identity
- district opinion / judgment, Ninth Circuit amended opinion, and Supreme Court petition / cert / argument / opinion proceedings
- plaintiff / defendant / appellant / appellee / petitioner / respondent / amicus participation
- one explicit case-lineage crosswalk across the three court levels
- crosswalks into San Rafael's legal posture and decision chain

It does **not** yet include:

- a direct capture of the San Francisco amicus brief PDF itself
- a direct district-court docket capture from a free court-hosted surface
- graph-v1 import scope changes in the same step

## Primary Artifacts

- [Grants Pass legal bundle](../data/normalized/legal-precedent-02/bundle-01.json)
- [District Opinion Extract](../data/extracted/grants-pass-district-opinion-order/2026-04-12.json)
- [District Judgment Extract](../data/extracted/grants-pass-district-judgment/2026-04-12.json)
- [Ninth Circuit Amended Opinion Extract](../data/extracted/ninth-circuit-grants-pass-amended-opinion/2026-04-12.json)
- [Supreme Court docket extract](../data/extracted/scotus-grants-pass-docket/2026-04-12.json)
- [Supreme Court opinion extract](../data/extracted/scotus-grants-pass-opinion/2026-04-12.json)
- [Supreme Court opinion text](../data/extracted/scotus-grants-pass-opinion/opinion.txt)
