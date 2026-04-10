# Marin Civic Graph

Marin Civic Graph is a planning repo for a Marin County civic-intelligence product.

The core idea is to build a searchable local graph of:

- institutions
- actors
- meetings
- agenda items
- decisions
- money
- documents
- issues
- places

The product should make it easier to answer questions like:

- Who decided this?
- Which meeting and agenda item covered it?
- Who spoke on it?
- Who voted?
- What documents justified it?
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
2. Meetings, agenda items, votes, speakers, documents
3. Campaign money, grants, contracts, and public disclosures
4. Entity resolution for recurring people and organizations

## Planning Docs

- [Project Brief](./docs/project-brief.md)
- [Borrow Map](./docs/borrow-map.md)
- [Schema v1](./docs/schema-v1.md)
- [Entity Glossary](./docs/entity-glossary.md)
- [Jurisdiction Source Map](./docs/jurisdiction-source-map.md)
- [Source Inventory](./docs/source-inventory.md)

## Current Status

This repo is for planning, schema design, source mapping, and architecture decisions before implementation begins.
