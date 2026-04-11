# Marin Civic Graph

Marin Civic Graph is a planning repo for a Marin County civic-intelligence product.

The core idea is to build a searchable local graph of:

- institutions
- actors
- meetings
- agenda items
- decisions
- projects
- money
- records
- issues
- places

The product should make it easier to answer questions like:

- Who decided this?
- Which meeting and agenda item covered it?
- Who spoke on it?
- Who voted?
- What records justified it?
- Which organizations, donors, contractors, or grantees were adjacent to the decision?

## Product Thesis

Local government is often formally public but practically obscure. The goal is not to invent a new theory of politics; it is to make institutional process legible.

The system should privilege primary-source evidence:

- agendas
- packets
- minutes
- videos
- contracts
- grants
- campaign filings
- Form 700 / Form 803 disclosures
- 990s
- court records where usable

## Non-Goals

- unsupported accusations encoded as facts
- partisan scorecards with no defensible methodology
- black-box "influence scores" as a primary data primitive
- overclaiming public will from weak or self-selected signals

## Initial Scope

Start narrow:

1. Marin County government and San Rafael
2. Meetings, agenda items, votes, speakers, records
3. Campaign money, grants, contracts, and public disclosures
4. Entity resolution for recurring people and organizations

## Planning Docs

- [Project Brief](./docs/project-brief.md)
- [Borrow Map](./docs/borrow-map.md)
- [Schema v1](./docs/schema-v1.md)
- [Graph Data Model](./docs/graph-data-model.md)
- [Graph Joins And Identity](./docs/graph-joins-and-identity.md)
- [Domain Expansion Matrix](./docs/domain-expansion-matrix.md)
- [Criminal Justice Submodel](./docs/criminal-justice-submodel.md)
- [Criminal Sample Basket Source Bundle](./docs/criminal-sample-basket-source-bundle.md)
- [Criminal Sample Basket Ingestion Checklist](./docs/criminal-sample-basket-ingestion-checklist.md)
- [Campaign Finance And Disclosure Submodel](./docs/campaign-finance-disclosures-submodel.md)
- [Campaign Finance Layer Source Bundle](./docs/campaign-finance-layer-source-bundle.md)
- [Campaign Finance Layer Ingestion Checklist](./docs/campaign-finance-layer-ingestion-checklist.md)
- [Campaign Finance Sample Basket Selection](./docs/campaign-finance-sample-basket-selection.md)
- [Procurement, Grants, Contracts, And Performance Submodel](./docs/procurement-grants-contracts-submodel.md)
- [Procurement Layer Source Bundle](./docs/procurement-layer-source-bundle.md)
- [Procurement Layer Ingestion Checklist](./docs/procurement-layer-ingestion-checklist.md)
- [Procurement Sample Basket Selection](./docs/procurement-sample-basket-selection.md)
- [Permits, Applications, And Denials Submodel](./docs/permits-applications-denials-submodel.md)
- [Permit Layer Source Bundle](./docs/permit-layer-source-bundle.md)
- [Permit Layer Ingestion Checklist](./docs/permit-layer-ingestion-checklist.md)
- [Permit Sample Basket Selection](./docs/permit-sample-basket-selection.md)
- [Record Model](./docs/record-model.md)
- [Judicial And Oversight Extension](./docs/judicial-and-oversight-extension.md)
- [Judicial Pressure-Test Basket Source Bundle](./docs/judicial-pressure-test-basket-source-bundle.md)
- [Judicial Pressure-Test Basket Ingestion Checklist](./docs/judicial-pressure-test-basket-ingestion-checklist.md)
- [Entity Glossary](./docs/entity-glossary.md)
- [Jurisdiction Source Map](./docs/jurisdiction-source-map.md)
- [Ingestion Agents](./docs/ingestion-agents.md)
- [Source Registry Format](./docs/source-registry-format.md)
- [Seed Source Registry](./registry/README.md)
- [Media Attribution Rules](./docs/media-attribution-rules.md)
- [Open Questions](./docs/open-questions.md)
- [Backlog](./docs/backlog.md)
- [Case Study 01](./docs/case-studies/01-san-rafael-homelessness.md)
- [Case Study 01 Ingestion Checklist](./docs/case-studies/01-san-rafael-homelessness-ingestion-checklist.md)
- [Case Study 01 Source Bundle](./docs/case-studies/01-san-rafael-homelessness-source-bundle.md)
- [Artifact Conventions](./docs/artifact-conventions.md)
- [Source Inventory](./docs/source-inventory.md)
- [Reference Notes](./docs/reference-notes.md)

## Data Layout

- [Data README](./data/README.md)
- [Raw Artifacts](./data/raw/README.md)
- [Extracted Outputs](./data/extracted/README.md)
- [Normalized Outputs](./data/normalized/README.md)
- [Bundle 01 Extracted Summary](./data/extracted/san-rafael-homelessness-01/bundle-01-summary.json)
- [Bundle 01 Normalized Summary](./data/normalized/san-rafael-homelessness-01/bundle-01.json)
- [Marin IJ Citation Layer](./data/normalized/san-rafael-homelessness-01/marin-ij-citation-layer.json)
- [Campaign Finance Sample Basket Bundle](./data/normalized/campaign-finance-sample-basket-01/bundle-01.json)
- [Item 5.a Split Map](./data/extracted/san-rafael-aug-19-2024-council-meeting/item-5a-record-splits.json)
- [Item 5.a Normalized Record Splits](./data/normalized/san-rafael-homelessness-01/aug-19-item-5a-record-splits.json)
- [Procurement Sample Basket Bundle](./data/normalized/procurement-sample-basket-01/bundle-01.json)
- [Permit Sample Basket Bundle](./data/normalized/permit-sample-basket-01/bundle-01.json)
- [P4134 Appeal Chain Split](./data/normalized/permit-sample-basket-01/p4134-appeal-chain.json)

## Scripts

- [Case Study 01 Extractor](./scripts/extract_case_study_01_bundle.py)

## Current Status

This repo started as a planning workspace and now includes the first live implementation slice:

- source registry seeds
- raw official source captures for case study 01
- raw criminal-justice source captures for Marin court and sheriff landing surfaces
- campaign-finance and disclosure layer formalized around `Election`, `Committee`, `Candidacy`, `Filing`, and `EconomicInterestDisclosure`
- campaign/disclosure source bundle and ingestion checklist for Marin County, San Rafael, and FPPC filing surfaces
- selected first campaign/disclosure sample basket:
  - `Mary Sackett for Marin County Supervisor 2026`
  - `Resource Conservation PAC, sponsored by Marin Resource Recovery`
  - `Quinn Gardner annual Form 700`
- first campaign/disclosure execution slice with:
  - direct raw HTML capture of the Marin NetFile campaign portal home
  - direct raw XML capture of the Marin campaign RSS feed
  - direct PDF captures for the selected Mary Sackett Form 497 and Resource Conservation PAC Form 460 filings
  - direct raw HTML capture of the San Rafael disclosures page and SEI portal
  - direct raw XML capture of the San Rafael SEI RSS feed
  - direct PDF capture of the selected Quinn Gardner Form 700
  - first normalized campaign basket linking `Committee`, `Candidacy`, `Filing`, `EconomicInterestDisclosure`, and campaign `MoneyFlow` candidates
  - official June 2, 2026 Marin County candidate-status page used to resolve Mary Sackett to `County Supervisor - District 1`
  - schedule-level extraction from the Resource Conservation PAC Form 460 used to promote sponsor inflows plus candidate and vendor outflows instead of leaving the PAC as a vague outside-money shell
- procurement-layer schema, source bundle, and checklist for Marin County and San Rafael funding and contract workflows
- selected first procurement sample basket:
  - county `Board Chambers Audio Visual Refresh / Prime Electric`
  - city `Downtown Library Renovation Project`
  - county `State and Local Fiscal Recovery Funds (SLFRF)`
- first procurement execution slice with:
  - direct raw HTML captures for the selected San Rafael project, procurement, meeting, and reopening pages
  - direct city PDF captures for the first and second Downtown Library amendment staff reports
  - direct city meeting, staff-report, and agenda-packet captures for the September 16, 2024 Downtown Library construction award
  - direct city grant-acceptance capture plus official California State Library award records for the Downtown Library state-funding lineage
  - transparent county text-proxy captures for blocked procurement, recovery-plan, and audit surfaces
  - first normalized procurement basket linking `Procurement`, `Agreement`, `Amendment`, `Program`, `PerformanceReview`, and `MoneyFlow` candidates
  - captured Marin County Granicus record set for Prime Electric `CB-6`: agenda page, staff report, attachment, and agreement
  - resolved county-side amount split for Prime Electric: `$994,866.17` contract, `$99,487` contingency, `$49,884` additional project costs, `$1,144,237` authorized project total
  - resolved the Downtown Library agreement-family boundary in favor of separate `Agreement` objects for Noll & Tam, Unger, and Unico under one shared project
  - resolved the Downtown Library state-funding claim into two California State Library grant relationships: a `$1,000,000` SB 129 / Building Forward award and a separate `$1,000,000` targeted design-process award
  - resolved the proxy-to-direct replacement rule: keep `source_id` and `record_id` stable, append new captures, and only change the preferred artifact reference when the semantic record is unchanged
- permit-layer schema, source bundle, and checklist for Marin County and San Rafael planning workflows
- first permit execution slice with raw captures for selected city and county project threads plus a normalized project-discovery bundle
- first appeal-chain split for P4134 with explicit determination, appeal, meeting, and decision candidates
- selected P4134 child-record captures preserved as proxy text snapshots for the HCR decision, consistency analysis, hearing notice, staff report, signed resolution, and appeal attachment
- extracted text and metadata for bundle 01
- a first normalized candidate bundle centered on the August 19, 2024 San Rafael homelessness decision chain
- a derived record-splitting layer for August 19 item `5.a`, including ordinance, resolution, contract, site-plan, code-of-conduct, and correspondence child records
