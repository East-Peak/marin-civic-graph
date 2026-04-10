# Judicial Pressure-Test Basket Source Bundle

Date drafted: April 10, 2026

This document turns the judicial / oversight pressure-test basket into a concrete first source bundle.

The goal is to pressure-test the legal and oversight model against multiple real-world patterns:

- local injunction and dismissal
- Supreme Court precedent
- appellate narrowing of an injunction
- settlement of surviving claims
- oversight report and recommendation structures

## Basket Overview

The first bundle should cover:

1. `Boyd v. City of San Rafael`
2. `City of Grants Pass v. Johnson`
3. `Coalition on Homelessness v. City and County of San Francisco`
4. Marin Civil Grand Jury homelessness / oversight material

## 1. Boyd v. City of San Rafael

### Why It Is In The Basket

- directly tied to case study 01
- clean bridge from litigation to ordinance / resolution / program rollout
- tests the local injunction -> dismissal -> implementation chain

### Existing Source Surfaces

- `san-rafael-boyd-dismissal-news-release`
  - https://www.cityofsanrafael.org/news-release-federal-judge-dismisses-lawsuit-limiting-city-regulation-of-camping-on-public-property/
- `san-rafael-grants-pass-explainer`
  - https://www.cityofsanrafael.org/supreme-courts-grants-pass-ruling-its-effect-on-san-rafaels-encampment-policy/
- `san-rafael-aug-19-2024-staff-report`
  - https://www.cityofsanrafael.org/documents/august-19-2024-staff-report-camping-ordinance-amendments-report-on-homelessness/
- `san-rafael-aug-19-2024-council-meeting`
  - https://www.cityofsanrafael.org/meetings/city-council-august-19-2024/

### First Records To Capture Or Promote

- city dismissal release
- August 19 staff report passages summarizing the injunction and dismissal
- August 19 minutes and resolution records
- sanctioned camping program pages that show the operational response

### Core Objects To Test

- `Case`
- `Record` with `legal_record` and `program_record`
- `Decision`
- `Program`
- `Claim` for the legal-constraint summary

### Known Gap

- still missing a clean public docket / order surface for the operative Boyd injunction and dismissal order

## 2. City of Grants Pass v. Johnson

### Why It Is In The Basket

- adds the Supreme Court layer
- gives a real docket pattern
- provides amicus and opinion structures that local governments respond to

### Source Surfaces

- `scotus-grants-pass-docket`
  - https://www.supremecourt.gov/docket/docketfiles/html/public/23-175.html
- `sf-city-attorney-grants-pass-amicus`
  - https://sfcityattorney.org/san-francisco-files-amicus-brief-with-u-s-supreme-court-in-grants-pass/
- `san-rafael-grants-pass-statement`
  - https://www.cityofsanrafael.org/city-of-san-rafael-statement-on-grants-pass-decision/
- `san-rafael-grants-pass-explainer`
  - https://www.cityofsanrafael.org/supreme-courts-grants-pass-ruling-its-effect-on-san-rafaels-encampment-policy/

### First Records To Capture Or Promote

- Supreme Court docket page
- linked Supreme Court opinion record
- SF City Attorney amicus explainer
- San Rafael statement and explainer records

### Core Objects To Test

- `Case`
- `CaseParticipation`
- `Record` with `legal_record`
- `Decision` and `Program` records that cite later legal posture

### Open Question

- whether we want a separate source entry for the opinion PDF itself or treat it as a child artifact discovered from the docket

## 3. Coalition on Homelessness v. City and County of San Francisco

### Why It Is In The Basket

- adds district-court injunction, Ninth Circuit narrowing, and settlement dynamics
- produces richer litigation stages than Boyd alone
- shows how a big-city operational lawsuit evolves after Grants Pass

### Source Surfaces

- `sf-city-attorney-coalition-injunction-appeal`
  - https://sfcityattorney.org/san-francisco-files-opening-brief-in-homeless-encampment-injunction-appeal/
- `sf-city-attorney-coalition-vacatur`
  - https://www.sfcityattorney.org/2024/07/08/ninth-circuit-vacates-part-of-injunction-in-homeless-encampment-lawsuit/
- `sf-city-attorney-coalition-narrowed-scope`
  - https://sfcityattorney.org/court-significantly-narrows-scope-of-homeless-encampment-lawsuit/
- `sf-city-attorney-coalition-settlement`
  - https://sfcityattorney.org/san-francisco-finalizes-settlement-in-homeless-encampment-lawsuit/

### First Records To Capture Or Promote

- injunction-appeal brief explainer
- Ninth Circuit vacatur statement
- narrowed-scope statement
- settlement statement
- linked PDF orders where publicly attached on the city attorney pages

### Core Objects To Test

- `Case`
- `Proceeding`
- `ReliefRequest`
- `Record`
- `CaseParticipation`
- `Claim` for surviving-claims / narrowed-scope summaries

### Known Gap

- full district-court docket coverage is still outside the first bundle

## 4. Marin Civil Grand Jury Homelessness / Oversight Material

### Why It Is In The Basket

- tests the non-judicial oversight branch
- provides report -> finding -> recommendation modeling
- stays local and directly relevant to Marin governance

### Source Surfaces

- `marin-civil-grand-jury-reports-index`
  - https://www.marincounty.gov/departments/grand-jury/civil-grand-jury-reports
- `marin-civil-grand-jury-homelessness-progress-report`
  - https://assets.marincounty.gov/marincounty-prod/public/2025-09/05.17.18%20Homelessness%20in%20Marin%20A%20Progress%20Report.pdf
- `marin-civil-grand-jury-report-names-prior-2018`
  - https://www.marincounty.gov/departments/grand-jury/report-names-prior-2018

### First Records To Capture Or Promote

- reports index page
- 2017-2018 homelessness report PDF
- report-title index page for older materials

### Core Objects To Test

- `OversightReport`
- `Finding`
- `Recommendation`
- `Record` with `legal_record` or dedicated oversight classification later if needed

### Known Gap

- older formal agency responses are not yet cleanly surfaced through the same modern index pages

## First Capture Order

The first pass should proceed in this order:

1. capture the Supreme Court docket page for `Grants Pass`
2. capture the SF City Attorney Coalition pages
3. promote the already-held San Rafael Boyd / Grants Pass records into case-linked objects
4. capture the Marin Civil Grand Jury index and the 2017-2018 homelessness report PDF

## What This Bundle Should Tell Us

After this bundle, we should know:

- which legal record types are truly worth first-class ingestion
- whether `Proceeding` and `ReliefRequest` need to exist immediately or can be deferred
- how much of litigation can be modeled from public official pages before deeper docket work
- whether `OversightReport`, `Finding`, `Recommendation`, and `AgencyResponse` are clean enough to justify first-class status

## Recommended Next Step

After registering these sources, create one focused extraction checklist that covers:

- `Boyd`
- `Grants Pass`
- `Coalition on Homelessness`
- one Marin Civil Grand Jury report

That should be the first legal / oversight implementation slice after the current San Rafael official bundle.
