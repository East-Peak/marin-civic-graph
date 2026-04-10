# Project Brief

## Working Name

Marin Civic Graph

Possible future product names:

- Marin Paper Trail
- Marin Power Map
- Marin Civic Search

## Problem

Marin public process is technically open but practically fragmented.

The public record is spread across:

- county and city meeting systems
- agendas and packets
- minutes and videos
- campaign finance filings
- disclosure forms
- contracts and grants
- local media coverage
- nonprofit and public-agency websites

This fragmentation makes it hard to answer simple, concrete questions about who shaped a decision and how.

## Thesis

Build a civic graph that joins:

- institutions
- officeholders and appointees
- decisions
- records
- money
- issue areas
- places

The system should help users trace process, not just consume headlines.

## Primary User Questions

- Who actually had authority over this issue?
- What body or department touched it?
- Which meeting and agenda item addressed it?
- What did the staff report, ordinance, resolution, packet, or article say?
- Who commented publicly?
- How did members vote?
- Which organizations, donors, grantees, or contractors show up repeatedly around the issue?

## Record Model

Records should be first-class graph nodes, not just attachments.

Examples:

- Marin IJ article
- ordinance
- resolution
- agenda
- packet
- minutes
- staff report
- contract
- campaign filing

This is important because many of the questions the product should answer are really record questions:

- which record introduced the claim?
- which record authorized the action?
- which record memorialized the vote?
- which record framed the issue for the public?

## V1 Surface Area

### 1. Issue Page

One page for a topic like homelessness, parking, sheltering, or public safety.

Should show:

- related decisions
- related meetings
- related organizations
- related money flows
- related media

### 2. Actor Page

One page for a person or organization.

Should show:

- roles and affiliations
- comments and appearances
- donations and money received
- contracts, grants, or board seats
- related issues and decisions

### 3. Decision Page

One page for a vote, ordinance, contract, or formal action.

Should show:

- governing body
- date
- agenda item
- supporting documents
- speakers
- vote breakdown
- implementation follow-through

## V1 Geography

Start with:

- Marin County
- San Rafael

Then expand to:

- Novato
- Mill Valley
- Sausalito
- Tiburon / Belvedere
- Fairfax / San Anselmo / Central Marin

## V1 Policy Themes

- homelessness / encampments / sheltering
- public safety
- parking / traffic / street design
- housing / land use
- contracts / grants / nonprofit service delivery

## Success Criteria

- A user can trace one real decision from issue to meeting to document to vote.
- A user can inspect one recurring actor across meetings, articles, and money.
- A user can compare formal public process with surrounding influence surfaces.

## Immediate Planning Deliverables

- verify official source surfaces for Marin County and San Rafael
- lock a small, stable vocabulary for nodes and relationships
- choose one case-study issue to pressure-test the model
