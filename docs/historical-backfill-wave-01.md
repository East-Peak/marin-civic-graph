# Historical Backfill Wave 01

Date drafted: April 11, 2026

This note converts the source-profile matrix into the first actual backfill plan.

Wave 01 is intentionally conservative.

The goal is to backfill the most stable, highest-value recurring civic surfaces before taking on the messier ones.

## Wave 01 Objective

Backfill core public-process and filing surfaces to at least:

- `2019-01-01`

for the jurisdictions already in scope:

- `San Rafael`
- `Marin County`

## Why These Sources First

Wave 01 should optimize for:

- durable archives
- high join value
- repeatable access patterns
- strong downstream graph yield

That means:

- meetings
- filings
- disclosure records

before:

- harder planning systems
- fragmented procurement detail
- court and criminal surfaces
- older paywalled media

## Wave 01 Scope

### Track A: San Rafael Council Process

Sources:

- `san-rafael-city-council-meetings`

Target:

- every council meeting from `2019-01-01` forward

Expected graph yield:

- `Meeting`
- `AgendaItem`
- `Decision`
- `VoteCast`
- `Record`

Reason:

- strongest city-side decision backbone
- many downstream contracts, ordinances, and implementation pages can be joined from here

### Track B: Marin County Board Process

Sources:

- `marin-county-bos-meetings`

Target:

- every BOS meeting from `2019-01-01` forward

Expected graph yield:

- `Meeting`
- `AgendaItem`
- `Decision`
- `VoteCast`
- `Record`

Reason:

- county-side equivalent of the San Rafael council backbone

### Track C: Marin County Campaign Finance

Sources:

- `marin-county-campaign-finance-netfile`
- `marin-county-campaign-finance-rss`

Target:

- local county campaign filings from `2019-01-01` forward where discoverable through RSS, committee history, or filing-image paths

Expected graph yield:

- `Committee`
- `Candidacy`
- `Filing`
- `MoneyFlow`
- `Election`

Reason:

- high recurring-actor value
- comparatively clean official surface

### Track D: San Rafael Form 700

Sources:

- `san-rafael-sei-netfile-portal`
- `san-rafael-sei-rss-feed`

Target:

- public Form 700 filings from `2019-01-01` forward, or earliest visible archive boundary if later

Expected graph yield:

- `EconomicInterestDisclosure`
- `Filing`
- `Actor`
- `Seat`

Reason:

- direct overlap with officeholders, boards, departments, and later actor-resolution work

### Track E: San Rafael Form 803

Sources:

- `san-rafael-public-records-form-803-search`

Target:

- all visible local Form 803 records from `2019-01-01` forward

Expected graph yield:

- `Filing`
- `MoneyFlow: behested_payment`
- `Actor`
- `SeatService`

Reason:

- small volume, high signal
- gives the project a cleaner disclosure layer than waiting for later

### Track F: San Rafael Campaign Financial Filings

Sources:

- `san-rafael-elections-index`
- `san-rafael-past-elections`
- `san-rafael-public-records-financial-filings-folder`
- `san-rafael-public-records-independent-expenditures-folder`
- election landing pages discovered through those indices

Target:

- backfill city-side campaign filings from `2019-01-01` forward using the city election indices as the discovery backbone and election landing pages as the current child-folder discovery surface, with direct folder enumeration only where anonymous Laserfiche listing actually works
- practical current reach is better than the original floor: campaign-bearing election pages currently run from `2011` through `2024`, plus the June 7, 2016 special-election page

Expected graph yield:

- `Committee`
- `Filing`
- `MoneyFlow`
- `Candidacy`
- `independent_expenditure` records

Reason:

- this is the missing city-side campaign surface needed for true local media-to-campaign overlaps
- the current working discovery pattern is `elections / past-elections -> election landing page -> campaign filing destination`
- within that pattern, pre-2020 campaign-bearing pages expose election-level folder IDs, while `2020+` pages expose candidate-specific folder IDs
- those same election pages also expose direct `DocView` records that can be captured as first-class election records even when folder enumeration remains flaky

## Wave 01 Exclusions

Do not include these in Wave 01:

- Marin County planning project pages with Cloudflare-heavy behavior
- San Rafael OpenGov planning system deep backfill
- procurement agreement family backfill beyond already selected samples
- criminal cases
- judicial dockets
- operator-assisted Marin IJ archive sweeps

Those are real targets, but they are not the right first mass backfill wave.

## Execution Order

1. San Rafael City Council meetings
2. Marin County Board of Supervisors meetings
3. Marin County campaign finance
4. San Rafael Form 700
5. San Rafael Form 803
6. San Rafael campaign financial filings
7. San Rafael independent expenditures

Reason:

- establish decision spines first
- then backfill money and disclosure layers that attach to those decision spines

## Adapter Requirements By Track

### Straightforward adapters

- San Rafael council meetings
- Marin County BOS meetings
- San Rafael Form 700 RSS / portal
- Marin County campaign RSS / filing images

### Session-aware adapters

- San Rafael Form 803 Laserfiche search
- San Rafael campaign financial filings folder
- San Rafael independent expenditures folder

## Minimum Deliverable For Wave 01

Wave 01 is successful when the repo has:

- a stable list of in-scope source IDs
- documented backfill boundaries
- one repeatable collection path per source family
- one manifest pattern for historical capture
- enough normalized output to test entity recurrence across:
  - meetings
  - city/county filings
  - disclosures

## Recurring Sync After Backfill

After a source family completes backfill, move it to recurring sync.

Default recurring cadence:

- `weekly`

Exceptions:

- `daily`
  - active campaign filing feeds near elections
  - high-churn council/BOS calendars if needed

- `monthly`
  - slower annual reporting surfaces

## Wave 01 Success Criterion

By the end of this wave, the graph should support:

- multi-year San Rafael council history
- multi-year Marin County BOS history
- multi-year county campaign history
- multi-year city disclosure history
- first city-side campaign filing history

That is enough to move the project from case-study prototyping into actual local historical continuity.
