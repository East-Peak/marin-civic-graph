# Source Profile Matrix

Date drafted: April 11, 2026

This document turns the source registry into something operational.

The goal is not just to list sources. It is to document where key record families actually live for each jurisdiction and what that implies for:

- adapter design
- historical backfill
- recurring sync

This first matrix covers:

- `San Rafael`
- `Marin County`

## Reading The Matrix

Each row is a source family, not a single URL.

The key questions are:

- where do these records actually live
- what platform family are we dealing with
- what access pattern does it require
- how far back should we try to backfill first
- what recurring cadence is justified after backfill

## San Rafael

| Source family | Primary surfaces | Platform family | Access pattern | Archive shape | Initial backfill target | Recurring cadence | Current state | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| City Council meetings | `san-rafael-city-council-meetings` | `wordpress_proudcity` | `static_public_page` + linked PDFs | archive page by meeting | `2019-01-01` | `weekly` | good | High-value backbone for decisions, votes, agenda items, and packets |
| Boards and commissions | `san-rafael-boards-and-commissions-index` | `wordpress_proudcity` | `static_public_page` | broad index, likely split by body | `2020-01-01` | `weekly` | discovery only | Needs body-by-body expansion |
| Planning commission / zoning administrator | `san-rafael-planning-commission-meetings`, `san-rafael-zoning-administrator-hearings` | `wordpress_proudcity` | `static_public_page` + linked records | archive-style meeting pages | `2020-01-01` | `weekly` | seeded | Good next-tier decision layer after council/BOS |
| Major planning projects / applications | `san-rafael-major-planning-projects`, `san-rafael-opengov-planning-category`, `san-rafael-apply-to-planning-online` | mixed `wordpress_proudcity` + external planning system | mixed public pages with external destination | project-by-project, not one clean archive | `2020-01-01` | `weekly` | partial | Discovery is on city pages; operative records may live elsewhere |
| Form 700 disclosures | `san-rafael-sei-netfile-portal`, `san-rafael-sei-rss-feed` | `netfile_campaign_portal` | public portal + RSS + direct filing image | filing history by filer / period | `2019-01-01` | `weekly` | strong | Best current city filing surface for structured disclosure backfill |
| Form 803 disclosures | `san-rafael-public-records-form-803-search`, `san-rafael-kate-colin-form-803-2025-09-04` | `laserfiche_public_records` | `cookie_aware_json` | searchable public-records corpus | `2019-01-01` | `weekly` | first live slice | Strong example of filing family living outside NetFile |
| Campaign financial filings | `san-rafael-public-records-financial-filings-folder` | `laserfiche_public_records` | `cookie_aware_json` probe + page-linked discovery | top-level folder plus child candidate folders | `2019-01-01` | `weekly` | partial | Destination confirmed; anonymous folder enumeration currently fails, so election pages are the current discovery backbone |
| Independent expenditures | `san-rafael-public-records-independent-expenditures-folder` | `laserfiche_public_records` | `cookie_aware_json` probe + page-linked discovery | folder-style archive plus source-linked direct records | `2019-01-01` | `weekly` | partial | Separate official destination from campaign filing folder; top-level listing currently does not yield a usable anonymous inventory |
| Procurement / bids / project awards | `san-rafael-bids-and-proposals`, city council meeting records, Downtown Library thread | mixed `wordpress_proudcity` + council packets | public page + linked packet PDFs | mixed archive / project pages | `2020-01-01` | `weekly` | usable | Actual agreement lineage often lives in council packets, not procurement page alone |
| Election / canvass pages | `san-rafael-elections-index`, `san-rafael-past-elections`, `san-rafael-june-8-2010-election`, `san-rafael-november-2-2010-election`, `san-rafael-november-8-2011-election`, `san-rafael-november-5-2013-election`, `san-rafael-november-3-2015-election`, `san-rafael-june-7-2016-election`, `san-rafael-november-7-2017-election`, `san-rafael-june-5-2018-special-municipal-election`, `san-rafael-november-6-2018-election`, `san-rafael-november-3-2020-election`, `san-rafael-november-8-2022-election`, `san-rafael-november-5-2024-election`, `san-rafael-june-2-2026-special-municipal-election` | `wordpress_proudcity` | `static_public_page` | election-index pages plus election-specific landing pages | `2010-01-01` for discovery, `2011-01-01` for campaign-bearing pages | `manual` | strong | City election indices are now the discovery backbone; older pages mostly expose election-level finance folders, while 2020+ pages expose candidate-specific folder IDs |

### San Rafael Idiosyncrasies

- Same city, different filing families, different systems:
  - `Form 700` lives on NetFile
  - `Form 803` lives in Laserfiche
  - campaign financial filings appear to live in a different Laserfiche folder
  - independent expenditures appear to live in yet another Laserfiche folder
- The public election pages can expose candidate-specific campaign-finance folder IDs even when the top-level Laserfiche browse URLs do not yield usable anonymous listings.
- The city's own `elections` and `past-elections` pages are the stable discovery backbone for historical election landing pages.
- The campaign-filing shape changes over time:
  - `2011` through `2018` pages plus the June 7, 2016 page expose election-level filing folders
  - `2020` through `2024` pages expose candidate-specific filing folders
  - `2010`, June 5, 2018 special, and June 2, 2026 special pages do not currently expose campaign-filing destinations
- The election pages also expose page-linked `DocView` records such as election-call resolutions, canvass/results resolutions, initiative records, and the independent-expenditure ordinance; those direct records are a stronger public capture path than anonymous folder enumeration.
- The public disclosures page is a routing surface, not the real data store.
- Many city policy, procurement, and implementation records are easiest to recover through council packets rather than program pages.
- San Rafael is a good first municipality precisely because it exposes this fragmentation in a manageable way.

## Marin County

| Source family | Primary surfaces | Platform family | Access pattern | Archive shape | Initial backfill target | Recurring cadence | Current state | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Board of Supervisors meetings | `marin-county-bos-meetings` | county meeting / packet portal | public meeting index + linked packets | archive page by meeting | `2019-01-01` | `weekly` | seeded | County decision backbone |
| Campaign finance | `marin-county-campaign-finance-netfile`, `marin-county-campaign-finance-rss` | `netfile_campaign_portal` | portal + RSS + direct document images | filer / committee history | `2019-01-01` | `weekly`, `daily` near election periods | strong | Best current county-side finance surface |
| Candidate status / election context | `marin-county-candidate-status-2026-06-02`, `marin-county-campaign-finance-guide` | county elections pages | public HTML but may be CLI-blocked | cycle-specific pages | `2020-01-01` | `manual` or `weekly` near election periods | partial | Good for seat/election joins, not enough by itself for filing backfill |
| County Form 700 guidance / election filing context | `marin-county-form-700` | county elections page | public page | guidance page | `latest_only` | `manual` | seeded | Useful as interpretation layer, not a high-volume record source |
| Planning projects / permits | `marin-county-planning-projects`, `marin-county-p5139-project-page`, `marin-county-p4134-*` | county planning pages with Cloudflare behavior | browser-visible but often CLI-blocked | project page + child PDFs | `2020-01-01` | `weekly` | partial | Strong content, awkward fetch mechanics; transparent proxy captures may remain necessary for some surfaces |
| Planning commission / DZA hearings | `marin-county-planning-commission-hearings`, `marin-county-deputy-zoning-administrator-hearings` | county hearing pages | mixed public HTML / linked PDFs | hearing-by-hearing pages | `2020-01-01` | `weekly` | seeded | Important bridge from applications to determinations and appeals |
| Procurement / contracting | `marin-county-contracting-opportunities`, `marin-county-procurement-division`, Prime Electric records | mixed county pages + meeting packets | public pages, some CLI-blocked | solicitation pages plus BOS packet lineage | `2020-01-01` | `weekly` | usable | As with San Rafael, operative approvals often live in Board records, not contracting page alone |
| Budget / metrics / recovery funds | `marin-county-budget-and-priority-setting`, `marin-county-service-metrics`, `marin-county-slfrf`, `marin-county-single-audit-reports` | county pages + PDF archives | mixed public HTML / PDFs, sometimes CLI-blocked | annual report sequence | `2020-01-01` | `monthly` | partial | Better for program and performance context than transaction-level data |
| Court / sheriff landing surfaces | court ePortal, judicial assignments, sheriff detention / warrants / records | mixed court and sheriff systems | public portals with varying access limits | current-state and search portals | `latest_only` for now | `manual` | exploratory | Keep out of general backfill wave until operator and privacy boundaries stay clear |

### Marin County Idiosyncrasies

- County planning and some budget/procurement pages are browser-visible but can be CLI-blocked in this environment.
- County campaign finance is much cleaner than county planning from a fetch perspective because NetFile exposes RSS and direct filing images.
- Board records remain the most reliable county-level source of operative approvals.
- County-wide backfill should start with BOS and campaign finance before trying to industrialize planning pages.

## Operational Conclusions

### Good first backfill families

- San Rafael City Council meetings
- Marin County Board of Supervisors meetings
- Marin County campaign finance
- San Rafael Form 700
- San Rafael Form 803
- San Rafael campaign-financial-filings folder

### Good second-wave families

- San Rafael planning commission / zoning administrator
- Marin County planning projects and hearings
- San Rafael procurement/agreement lineages through council packets
- Marin County procurement/agreement lineages through BOS packets

### Defer or isolate

- criminal justice backfill
- court case backfill
- older paywalled media

Those need stronger operator and methodology boundaries than the first municipal backfill wave.
