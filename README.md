# Open Marin

A civic-intelligence graph platform built on public Marin County records — a portfolio project demonstrating data engineering, graph ML, and full-stack work. The current implementation runs against a live Neo4j AuraDB at production scale: ~114K nodes / ~148K edges across 11 jurisdictions and 21 canonical entity types.

What's in the repo:

- **Reproducible Python ingestion + projection pipelines** (~80 scripts under [`scripts/`](./scripts/)) that pull from FPPC NetFile, CourtListener, Socrata, civic-tech meeting platforms (Granicus, CivicPlus, ProudCity, Drupal), and Form 700 PDFs.
- **A v2 architecture** ([`docs/specs/2026-04-26-open-marin-v2-design.md`](./docs/specs/2026-04-26-open-marin-v2-design.md)) for a Cosmograph-rendered "Constellation" hero view, with UMAP-projected semantic embeddings (Voyage `voyage-4`, 1024-d), HDBSCAN clustering with Hungarian-matched stable IDs across runs, and atomic Cypher promotion of derived state.
- **A Next.js 16 / React 19 / TypeScript 5 frontend** with shared Python↔TypeScript model contracts, vendor-import lint enforcement at both the Python and TS layers, and ~423 frontend tests.
- **Adversarial review discipline.** The v2 architecture spec went through 19 rounds of Codex (gpt-5.4 high-reasoning) review until convergence. Every commit pairs with a co-authoring trailer crediting the AI tool used. The repo treats AI as a serious engineering collaborator, not autocomplete.

## A short tour

A handful of the most representative pieces:

- [`scripts/build_umap.py`](./scripts/build_umap.py) — UMAP projection pipeline with a closed-form 4-parameter similarity-transform alignment (Umeyama 1991) so weekly fits don't rotate, mirror, or rescale the layout. Tested at machine epsilon in [`tests/test_build_umap.py`](./tests/test_build_umap.py).
- [`scripts/outbound_policy.py`](./scripts/outbound_policy.py) — vendor-call gatekeeper (default-deny eligibility, per-type field redaction, neighbor-filtering for graph-aware enforcement, JSONL audit log on every outbound call). Direct vendor SDK imports outside this module are blocked by [`scripts/_lint_check_outbound.py`](./scripts/_lint_check_outbound.py) AND ESLint's `no-restricted-imports` rule.
- [`scripts/publish_constellation.py`](./scripts/publish_constellation.py) — atomic 4-step Cypher promote (snapshot → demote → promote → manifest pointer) with a hard drift-budget gate per the design spec, all-or-nothing in a single transaction.
- [`scripts/citations.py`](./scripts/citations.py) + [`app/src/lib/citations.ts`](./app/src/lib/citations.ts) — node-level provenance check (`has_primary_source_citation`) implemented as a synchronized Python↔TypeScript pair so the same eligibility rule runs on both sides of the wire.
- [`app/src/tests/lib/server/data-queries.test.ts`](./app/src/tests/lib/server/data-queries.test.ts) — Cypher-injection sweep across all 10 predefined query templates with deliberately hostile inputs.

## Status

- **v1 graph in production** at AuraDB (~114K nodes / ~148K edges, 11 Marin jurisdictions, 21 canonical node types).
- **Plan v2.0 (benchmarks + foundation) shipped 2026-04-29.** The full v2 pipeline ran end-to-end against the live AuraDB; the Constellation is live in the database. Production rehearsal report at [`docs/benchmarks/2026-04-29-v2-rehearsal.md`](./docs/benchmarks/2026-04-29-v2-rehearsal.md). Of 9 pass criteria: 4 measured PASS (UMAP fit time, HDBSCAN compute, outbound-leak audit, manifest round-trip), 1 N/A (drift alignment — first run, no prior frame to align against), 1 FAIL (payload size — calibration miss, fixable by spec amendment), 3 DEFERRED to manual browser test (first-paint, FPS, sprite throughput). Verdict: **PROVISIONAL GO**.
- **v2.1 (Constellation MVP) is next** — full Cosmograph integration, sprite atlas tiering, region-label rendering, full pipeline cutover.

## Tech stack

Python 3.14, Neo4j AuraDB 5.x with vector indexes, `umap-learn`, `hdbscan`, `scipy`, Voyage AI (`voyage-4` embeddings), Anthropic Claude (Haiku 4.5 for cluster naming, Opus 4.7 1M-context for engineering work), Next.js 16 App Router, React 19, TypeScript 5, Tailwind 4, `@cosmograph/cosmos` (MIT WebGL renderer), `vitest`, `pytest`.

## What this is, and isn't

This repo is a **portfolio piece**, not an open-source product:

- **It's runnable.** The pipelines, frontend, and tests all run; the v1 graph is live in AuraDB. You're welcome to read, learn from, and reference the architecture decisions.
- **It's not maintained for community use.** Bug reports and feature requests aren't being triaged. There's no CONTRIBUTING.md and no roadmap commitment outside what's in [`docs/specs/`](./docs/specs/).
- **It's not licensed for redistribution.** The code is provided source-available under [PolyForm Noncommercial 1.0](./LICENSE) — read, study, fork-locally, but no commercial use or redistribution. Public-record data artifacts are not relicensed.
- **The data is not a product.** All entity data is reconstructed from public sources cited in [`docs/specs/2026-04-14-marin-civic-graph-v1-design.md`](./docs/specs/2026-04-14-marin-civic-graph-v1-design.md). Anyone in the data who wants their public-record information removed from this projection should reach out via the commit trailer email.

The work below the cut is the original product brief — useful as context for why the architecture looks the way it does.

---

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
- [Graph Materialization Proposal](./docs/graph-materialization-proposal.md)
- [Architecture Review Checklist](./docs/internal/architecture-review-checklist.md)
- [Schema Review Response](./docs/internal/schema-review-response.md)
- [Graph Query Pack](./docs/graph-query-pack.md)
- [Question Set V1](./docs/question-set-v1.md)
- [Claude Collaboration Handoff](./docs/internal/claude-collaboration-handoff.md)
- [Daily Log 2026-04-13](./docs/internal/daily-log-2026-04-13.md)
- [Daily Log 2026-04-14](./docs/internal/daily-log-2026-04-14.md)
- [Graph View Layer](./docs/graph-view-layer.md)
- [Graph Read-Model Contracts](./docs/graph-read-model-contracts.md)
- [Ralph Loop Plan](./docs/internal/ralph-loop-plan.md)
- [Controlled Breadth Sprint Proposal](./docs/internal/breadth-sprint-proposal.md)
- [Controlled Breadth Sprint Adversarial Review Checklist](./docs/internal/breadth-sprint-review-checklist.md)
- [Decision Log](./docs/internal/decision-log.md)
- [Graph Joins And Identity](./docs/graph-joins-and-identity.md)
- [Identity Resolution Submodel](./docs/identity-resolution-submodel.md)
- [Actor Resolution Worked Example](./docs/actor-resolution-worked-example.md)
- [Media Mention And Claim Worked Example](./docs/media-mention-claim-worked-example.md)
- [Media Recurrence Worked Example](./docs/media-recurrence-worked-example.md)
- [Media Cross-Domain Worked Example](./docs/media-cross-domain-worked-example.md)
- [Media Disclosure Overlap Worked Example](./docs/media-disclosure-overlap-worked-example.md)
- [Media Outside-Money Overlap Worked Example](./docs/media-outside-money-overlap-worked-example.md)
- [Domain Expansion Matrix](./docs/domain-expansion-matrix.md)
- [Criminal Justice Submodel](./docs/criminal-justice-submodel.md)
- [Criminal Sample Basket Source Bundle](./docs/criminal-sample-basket-source-bundle.md)
- [Criminal Sample Basket Ingestion Checklist](./docs/criminal-sample-basket-ingestion-checklist.md)
- [Campaign Finance And Disclosure Submodel](./docs/campaign-finance-disclosures-submodel.md)
- [Campaign Finance Layer Source Bundle](./docs/campaign-finance-layer-source-bundle.md)
- [Campaign Finance Layer Ingestion Checklist](./docs/campaign-finance-layer-ingestion-checklist.md)
- [Campaign Finance Sample Basket Selection](./docs/campaign-finance-sample-basket-selection.md)
- [Campaign Finance Form 803 Slice](./docs/campaign-finance-form-803-slice.md)
- [Reconciliation And Anomaly Model](./docs/reconciliation-and-anomaly-model.md)
- [Selected San Rafael Form 460 OCR Capture](./docs/campaign-form460-ocr-capture.md)
- [San Rafael Form 460 PDF Export Capture](./docs/campaign-form460-pdf-export.md)
- [San Rafael Form 460 Schedule Extraction](./docs/campaign-form460-schedule-extraction.md)
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
- [Legal Precedent 01](./docs/legal-precedent-01.md)
- [Legal Precedent 02](./docs/legal-precedent-02.md)
- [Entity Glossary](./docs/entity-glossary.md)
- [Jurisdiction Source Map](./docs/jurisdiction-source-map.md)
- [Ingestion Agents](./docs/ingestion-agents.md)
- [Source Registry Format](./docs/source-registry-format.md)
- [Source Adapter And Operations Plan](./docs/source-adapter-and-operations-plan.md)
- [Source Profile Matrix](./docs/source-profile-matrix.md)
- [Historical Backfill Wave 01](./docs/internal/historical-backfill-wave-01.md)
- [Seed Source Registry](./registry/README.md)
- [View Target Manifest](./registry/view-targets.yaml)
- [Question Set Manifest](./registry/question-set-v1.yaml)
- [Active Ralph Loop Manifest](./registry/loop-manifests/san-rafael-city-campaign-money-01.json)
- [Media Attribution Rules](./docs/media-attribution-rules.md)
- [Open Questions](./docs/internal/open-questions.md)
- [Backlog](./docs/internal/backlog.md)
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
- [Projected Outputs](./data/projected/README.md)
- [Graph V1 Projection Report](./data/projected/graph-v1/report.json)
- [Graph V1 Node Projection](./data/projected/graph-v1/nodes.jsonl)
- [Graph V1 Edge Projection](./data/projected/graph-v1/edges.jsonl)
- [Graph V1 Cypher Loader Output](./data/projected/graph-v1/load-graph-v1.cypher)
- [Graph Query Pack Report](./data/projected/graph-v1/query-pack-report.json)
- [Graph Query Pack Summary](./data/projected/graph-v1/query-pack-report.md)
- [Graph View Index](./data/projected/graph-v1/views/index.json)
- [Graph View Summary](./data/projected/graph-v1/views/summary.md)
- [Local Graph Viewer Shell](./viewer/index.html)
- [Kate Colin Actor Dossier](./data/projected/graph-v1/views/actor-kate-colin-dossier.json)
- [Rachel Kertz Actor Dossier](./data/projected/graph-v1/views/actor-rachel-kertz-dossier.json)
- [Downtown Streets Team Organization Dossier](./data/projected/graph-v1/views/organization-downtown-streets-team-dossier.json)
- [Resolution 15336 Decision Dossier](./data/projected/graph-v1/views/decision-2024-08-19-resolution-15336-dossier.json)
- [Boyd Case Dossier](./data/projected/graph-v1/views/case-boyd-v-city-of-san-rafael-dossier.json)
- [Sanctioned Camping Program Dossier](./data/projected/graph-v1/views/program-san-rafael-sanctioned-camping-dossier.json)
- [Camping Ordinance Implementation Program Dossier](./data/projected/graph-v1/views/program-san-rafael-camping-ordinance-implementation-dossier.json)
- [Building Forward Program Dossier](./data/projected/graph-v1/views/program-csl-building-forward-dossier.json)
- [Downtown Library Project Dossier](./data/projected/graph-v1/views/project-downtown-library-renovation-dossier.json)
- [San Rafael Jurisdiction Delivery Summary](./data/projected/graph-v1/views/jurisdiction-san-rafael-delivery-summary.json)
- [San Rafael Decision Money Rollup](./data/projected/graph-v1/views/decision-money-san-rafael-rollup.json)
- [San Rafael Decision Money Explanation](./data/projected/graph-v1/views/decision-money-san-rafael-explanation.json)
- [Sanctioned Camping Local Pressure Summary](./data/projected/graph-v1/views/program-san-rafael-sanctioned-camping-local-pressure-summary.json)
- [Camping Ordinance Implementation Local Pressure Summary](./data/projected/graph-v1/views/program-san-rafael-camping-ordinance-implementation-local-pressure-summary.json)
- [San Rafael Local Pressure Comparison](./data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-comparison.json)
- [San Rafael Local Pressure Explanation](./data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-explanation.json)
- [San Rafael Jurisdiction Legal Constraint Summary](./data/projected/graph-v1/views/jurisdiction-san-rafael-legal-constraint-summary.json)
- [Money Overlap Summary](./data/projected/graph-v1/views/money-overlap-summary.json)
- [Legal Constraint View](./data/projected/graph-v1/views/legal-constraint-view.json)
- [Validation Queue](./data/projected/graph-v1/views/validation-queue.json)
- [Bundle 01 Extracted Summary](./data/extracted/san-rafael-homelessness-01/bundle-01-summary.json)
- [Bundle 01 Normalized Summary](./data/normalized/san-rafael-homelessness-01/bundle-01.json)
- [Marin IJ Citation Layer](./data/normalized/san-rafael-homelessness-01/marin-ij-citation-layer.json)
- [Marin IJ 2024-08-24 Mention/Claim Example](./data/normalized/san-rafael-homelessness-01/marin-ij-2024-08-24-mention-claim-example.json)
- [Marin IJ Recurrence Example](./data/normalized/san-rafael-homelessness-01/marin-ij-recurrence-example-01.json)
- [Media Cross-Domain Join Example](./data/normalized/san-rafael-homelessness-01/media-cross-domain-join-example-01.json)
- [Media Disclosure Overlap Example](./data/normalized/san-rafael-homelessness-01/media-disclosure-overlap-example-01.json)
- [Media Outside-Money Overlap Example](./data/normalized/san-rafael-homelessness-01/media-outside-money-overlap-example-01.json)
- [San Rafael City Campaign IE Bundle](./data/normalized/san-rafael-city-campaign-ie-01/bundle-01.json)
- [San Rafael City Campaign Form 460 OCR Bundle](./data/normalized/san-rafael-city-campaign-form460-ocr-01/bundle-01.json)
- [San Rafael City Campaign Form 460 PDF Bundle](./data/normalized/san-rafael-city-campaign-form460-pdf-01/bundle-01.json)
- [San Rafael City Campaign Form 460 Schedule Bundle](./data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)
- [San Rafael City Campaign Form 460 PDF Extract](./data/extracted/san-rafael-city-campaign-form460-pdf-export/2026-04-12.json)
- [San Rafael City Campaign Form 460 Schedule Extract](./data/extracted/san-rafael-city-campaign-form460-schedules/2026-04-12.json)
- [San Rafael City Campaign Form 460 OCR Extract 2026-04-13](./data/extracted/san-rafael-city-campaign-form460-ocr/2026-04-13.json)
- [San Rafael City Campaign Form 460 PDF Extract 2026-04-13](./data/extracted/san-rafael-city-campaign-form460-pdf-export/2026-04-13.json)
- [San Rafael City Campaign Form 460 Schedule Extract 2026-04-13](./data/extracted/san-rafael-city-campaign-form460-schedules/2026-04-13.json)
- [Campaign Finance Sample Basket Bundle](./data/normalized/campaign-finance-sample-basket-01/bundle-01.json)
- [Campaign Finance Form 803 Slice Bundle](./data/normalized/campaign-finance-form-803-slice-01/bundle-01.json)
- [San Rafael Officeholder Disclosure Bundle](./data/normalized/san-rafael-officeholder-disclosures-01/bundle-01.json)
- [San Rafael City Campaign Evidence Record Bundle](./data/normalized/san-rafael-city-campaign-records-01/bundle-01.json)
- [San Rafael City Campaign Actor Supplement Bundle](./data/normalized/san-rafael-city-campaign-actors-01/bundle-01.json)
- [San Rafael Actor Completeness Bundle](./data/normalized/san-rafael-actor-completeness-01/bundle-01.json)
- [Grant Program Support Bundle](./data/normalized/grant-program-dossiers-01/bundle-01.json)
- [San Rafael Camping Ordinance Program Support Bundle](./data/normalized/san-rafael-camping-ordinance-program-01/bundle-01.json)
- [Project Dossier Support Bundle](./data/normalized/project-dossiers-01/bundle-01.json)
- [Canonical Issue Seed Bundle](./data/normalized/canonical-issues-01.json)
- [San Rafael Canonical Seed Bundle](./data/normalized/canonical-seeds-san-rafael-01.json)
- [San Rafael City Council Archive Inventory](./data/extracted/san-rafael-city-council-meetings/2026-04-11.json)
- [San Rafael City Council Meeting Page Capture](./data/extracted/san-rafael-city-council-meeting-pages/2026-04-12.json)
- [San Rafael City Council Minutes Capture](./data/extracted/san-rafael-city-council-minutes/2026-04-12.json)
- [San Rafael City Council Backbone Bundle](./data/normalized/san-rafael-city-council-backbone-01/bundle-01.json)
- [San Rafael City Council Decision Bundle](./data/normalized/san-rafael-city-council-decisions-01/bundle-01.json)
- [Marin County BOS Archive Inventory](./data/extracted/marin-county-bos-meetings/2026-04-11.json)
- [Marin County Campaign Finance Yearly Export Inventory](./data/extracted/marin-county-campaign-finance-yearly-exports/2026-04-11.json)
- [San Rafael Form 700 Backfill Inventory](./data/extracted/san-rafael-sei-netfile-portal/2026-04-12.json)
- [San Rafael City-Side Campaign Filing Inventory](./data/extracted/san-rafael-city-side-campaign-filings/2026-04-11.json)
- [San Rafael Election Direct Records](./data/extracted/san-rafael-election-direct-records/2026-04-11.json)
- [San Rafael Election Record Bundle](./data/normalized/san-rafael-election-records-01/bundle-01.json)
- [Item 5.a Split Map](./data/extracted/san-rafael-aug-19-2024-council-meeting/item-5a-record-splits.json)
- [Item 5.a Normalized Record Splits](./data/normalized/san-rafael-homelessness-01/aug-19-item-5a-record-splits.json)
- [Procurement Sample Basket Bundle](./data/normalized/procurement-sample-basket-01/bundle-01.json)
- [Permit Sample Basket Bundle](./data/normalized/permit-sample-basket-01/bundle-01.json)
- [P4134 Appeal Chain Split](./data/normalized/permit-sample-basket-01/p4134-appeal-chain.json)
- [Boyd Dismissal-Order Extract](./data/extracted/san-rafael-boyd-dismissal-order/2026-04-12.json)
- [Boyd TRO Extract](./data/extracted/san-rafael-boyd-tro-order/2026-04-12.json)
- [Boyd Preliminary-Injunction Extract](./data/extracted/san-rafael-boyd-preliminary-injunction-order/2026-04-12.json)
- [Legal Precedent 01 Bundle](./data/normalized/legal-precedent-01/bundle-01.json)
- [Grants Pass District Opinion Extract](./data/extracted/grants-pass-district-opinion-order/2026-04-12.json)
- [Grants Pass District Judgment Extract](./data/extracted/grants-pass-district-judgment/2026-04-12.json)
- [Grants Pass Ninth Circuit Extract](./data/extracted/ninth-circuit-grants-pass-amended-opinion/2026-04-12.json)
- [Grants Pass Docket Extract](./data/extracted/scotus-grants-pass-docket/2026-04-12.json)
- [Grants Pass Opinion Extract](./data/extracted/scotus-grants-pass-opinion/2026-04-12.json)
- [Legal Precedent 02 Bundle](./data/normalized/legal-precedent-02/bundle-01.json)

## Scripts

- [Case Study 01 Extractor](./scripts/extract_case_study_01_bundle.py)
- [San Rafael Form 803 Capture Workflow](./scripts/capture_san_rafael_form803.py)
- [San Rafael Form 700 Backfill Workflow](./scripts/capture_san_rafael_form700_backfill.py)
- [San Rafael Officeholder Disclosure Normalizer](./scripts/normalize_san_rafael_officeholder_disclosures.py)
- [San Rafael Election Page Discovery Helpers](./scripts/san_rafael_election_pages.py)
- [San Rafael Election Page Capture Workflow](./scripts/capture_san_rafael_election_pages.py)
- [San Rafael City Council Archive Capture Workflow](./scripts/capture_san_rafael_city_council_archive.py)
- [San Rafael City Council Meeting Page Capture Workflow](./scripts/capture_san_rafael_city_council_pages.py)
- [San Rafael City Council Minutes Capture Workflow](./scripts/capture_san_rafael_city_council_minutes.py)
- [San Rafael City Council Backbone Normalizer](./scripts/normalize_san_rafael_city_council_backbone.py)
- [San Rafael City Council Decision Normalizer](./scripts/normalize_san_rafael_city_council_decisions.py)
- [San Rafael City-Side Campaign Filing Inventory Workflow](./scripts/capture_san_rafael_city_campaign_filing_inventory.py)
- [San Rafael Election Direct Record Capture Workflow](./scripts/capture_san_rafael_election_direct_records.py)
- [San Rafael Election Direct Record Normalizer](./scripts/normalize_san_rafael_election_direct_records.py)
- [San Rafael Form 460 OCR Capture Workflow](./scripts/capture_san_rafael_city_campaign_form460_ocr.py)
- [San Rafael Form 460 PDF Export Workflow](./scripts/capture_san_rafael_city_campaign_form460_pdf_exports.py)
- [San Rafael Form 460 Schedule Extractor](./scripts/extract_san_rafael_city_campaign_form460_schedules.py)
- [San Rafael City Campaign Loop Helper](./scripts/san_rafael_city_campaign_loop_lib.py)
- [San Rafael City Campaign Evidence Record Normalizer](./scripts/normalize_san_rafael_city_campaign_records.py)
- [San Rafael City Campaign Actor Supplement Normalizer](./scripts/normalize_san_rafael_city_campaign_actors.py)
- [San Rafael Actor Completeness Normalizer](./scripts/normalize_san_rafael_actor_completeness.py)
- [Grant Program Dossier Support Normalizer](./scripts/normalize_grant_program_dossiers.py)
- [Project Dossier Support Normalizer](./scripts/normalize_project_dossiers.py)
- [Boyd Legal Bundle Normalizer](./scripts/normalize_legal_precedent_boyd.py)
- [Grants Pass Legal Bundle Normalizer](./scripts/normalize_legal_precedent_grants_pass.py)
- [Graph Projection Helper](./scripts/graph_projection_lib.py)
- [Graph Projection Builder](./scripts/build_graph_projection.py)
- [Graph Projection Smoke Checks](./scripts/graph_smoke_checks.py)
- [Graph Query Pack Runner](./scripts/run_graph_query_pack.py)
- [Graph View Builder](./scripts/build_graph_views.py)
- [Local Graph View Server](./scripts/serve_graph_views.py)
- [Neo4j V1 Loader](./scripts/load_neo4j_v1.py)
- [Marin County BOS Archive Capture Workflow](./scripts/capture_marin_county_bos_archive.py)
- [Marin County Campaign Finance Export Capture Workflow](./scripts/capture_marin_county_campaign_finance_exports.py)
