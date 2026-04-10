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
- [Item 5.a Split Map](./data/extracted/san-rafael-aug-19-2024-council-meeting/item-5a-record-splits.json)
- [Item 5.a Normalized Record Splits](./data/normalized/san-rafael-homelessness-01/aug-19-item-5a-record-splits.json)

## Scripts

- [Case Study 01 Extractor](./scripts/extract_case_study_01_bundle.py)

## Current Status

This repo started as a planning workspace and now includes the first live implementation slice:

- source registry seeds
- raw official source captures for case study 01
- raw criminal-justice source captures for Marin court and sheriff landing surfaces
- permit-layer schema, source bundle, and checklist for Marin County and San Rafael planning workflows
- extracted text and metadata for bundle 01
- a first normalized candidate bundle centered on the August 19, 2024 San Rafael homelessness decision chain
- a derived record-splitting layer for August 19 item `5.a`, including ordinance, resolution, contract, site-plan, code-of-conduct, and correspondence child records
