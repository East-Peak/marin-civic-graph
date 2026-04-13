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
- [Graph Materialization Proposal](./docs/graph-materialization-proposal.md)
- [Architecture Review Checklist](./docs/architecture-review-checklist.md)
- [Graph Query Pack](./docs/graph-query-pack.md)
- [Ralph Loop Plan](./docs/ralph-loop-plan.md)
- [Controlled Breadth Sprint Proposal](./docs/breadth-sprint-proposal.md)
- [Controlled Breadth Sprint Adversarial Review Checklist](./docs/breadth-sprint-review-checklist.md)
- [Decision Log](./docs/decision-log.md)
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
- [Historical Backfill Wave 01](./docs/historical-backfill-wave-01.md)
- [Seed Source Registry](./registry/README.md)
- [Active Ralph Loop Manifest](./registry/loop-manifests/san-rafael-city-campaign-money-01.json)
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
- [Projected Outputs](./data/projected/README.md)
- [Graph V1 Projection Report](./data/projected/graph-v1/report.json)
- [Graph V1 Node Projection](./data/projected/graph-v1/nodes.jsonl)
- [Graph V1 Edge Projection](./data/projected/graph-v1/edges.jsonl)
- [Graph V1 Cypher Loader Output](./data/projected/graph-v1/load-graph-v1.cypher)
- [Graph Query Pack Report](./data/projected/graph-v1/query-pack-report.json)
- [Graph Query Pack Summary](./data/projected/graph-v1/query-pack-report.md)
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
- [Boyd Legal Bundle Normalizer](./scripts/normalize_legal_precedent_boyd.py)
- [Grants Pass Legal Bundle Normalizer](./scripts/normalize_legal_precedent_grants_pass.py)
- [Graph Projection Helper](./scripts/graph_projection_lib.py)
- [Graph Projection Builder](./scripts/build_graph_projection.py)
- [Graph Projection Smoke Checks](./scripts/graph_smoke_checks.py)
- [Graph Query Pack Runner](./scripts/run_graph_query_pack.py)
- [Neo4j V1 Loader](./scripts/load_neo4j_v1.py)
- [Marin County BOS Archive Capture Workflow](./scripts/capture_marin_county_bos_archive.py)
- [Marin County Campaign Finance Export Capture Workflow](./scripts/capture_marin_county_campaign_finance_exports.py)

## Current Status

This repo started as a planning workspace and now includes the first live implementation slice:

- first graph-materialization scaffold for the narrowed San Rafael governance spine:
  - explicit import manifest at [import-manifest.yaml](./registry/import-manifest.yaml)
  - projection builder that narrows bundle-local JSON into one graph envelope
  - JSONL node/edge projection plus a generated Cypher loader output under [data/projected](./data/projected/README.md)
  - fixed five-query checkpoint now runs directly against the projected graph payload, so breadth decisions can be gated without relying on a live Neo4j session
  - smoke checks that prove actor, seat-service, filing, money, decision, record, and validation continuity end to end
  - evidence completeness is now backed by a dedicated San Rafael city-side campaign evidence-record bundle that promotes OCR/PDF/folder artifacts already referenced from filings, money flows, validation checks, and the narrow actor supplement
  - a narrow actor and issue supplement now lands `8` conservative campaign actors and `3` canonical issues without widening into discovery-stage review material
  - the first breadth-sprint council slice now adds `263` citywide `Meeting` nodes and `264` council `Record` nodes backed by captured meeting pages
  - the second breadth-sprint council slice now adds `220` captured minutes `Record` nodes plus a conservative citywide minutes-first decision layer with `3175` `AgendaItem` candidates and `1453` `Decision` candidates
  - graph-v1 is now at `6068` nodes and `20251` edges, with `1472` `Decision` nodes, `2970` `AgendaItem` nodes, `147` `MoneyFlow` nodes, and `16` bounded `ValidationCheck` nodes after projection merging
  - consent votes are now modeled conservatively: one section-level voted decision, with subitem outcomes linked back to that consent action instead of pretending each subitem had its own roll call
  - the elected-disclosure breadth slice now adds `9` current-officeholder Form `700` filings and `9` `EconomicInterestDisclosure` nodes backed by the public NetFile export and explicit current `SeatService` start dates
  - the current projection report still shows `missing_target:Actor = 147`; `Issue` and `Record` completeness gaps are no longer part of graph-v1
  - the current fixed-query-pack run now passes all five queries
  - the first Ralph-loop campaign-money batch recovered enough `2020` QA-backed money to move `Q4` from fail to pass without importing noisy OCR actors
  - the same batch required a validation-suppression rule for sparse older filings, so the queue now stays bounded at `16` checks across `5` subject filings instead of exploding into empty-reference noise
  - the first live local Neo4j load and query pass has been run successfully against the projected graph, proving end-to-end continuity for actor, seat-service, filing, money, decision, issue, and validation queries
- first normalized legal bundle now exists as `legal-precedent-01`:
  - captured the Boyd TRO, preliminary-injunction, and dismissal orders as durable PDF-backed legal records
  - the dismissal order is court-origin from the city-linked PDF; the TRO and preliminary-injunction orders are strong public filed-order copies from the Civil Rights Litigation Clearinghouse
  - extracted a durable court-timeline surface for complaint, TRO, preliminary injunction, dismissal-motion, hearing, and dismissal stages
  - normalized the first `Case`, `Proceeding`, and `CaseParticipation` objects for `Boyd v. City of San Rafael`
  - tied that case back into the August 19, 2024 item `5.a` ordinance / resolution chain and the sanctioned-camping program
  - preserved the remaining provenance gap explicitly: the TRO and preliminary-injunction orders are captured as public filed-order copies, not yet from a court-hosted docket surface
- second normalized legal bundle now exists as `legal-precedent-02`:
  - captured the District of Oregon opinion and judgment, the official Ninth Circuit amended opinion, and the official Supreme Court docket and slip opinion for `City of Grants Pass v. Johnson`
  - normalized district, appellate, and Supreme Court `Case`, `Proceeding`, and `CaseParticipation` objects plus an explicit case-lineage crosswalk
  - tied San Rafael's June 28 statement, September 2 explainer, and the August 19 response chain back to the Supreme Court precedent through an explicit crosswalk
  - preserved the remaining supporting-provenance gap explicitly: the San Francisco amicus brief PDF and a direct district-court docket surface are not yet captured
- source registry seeds
- source-registry format now expanded to capture platform family, backfill target, change signal, and source-specific quirks
- source-adapter operations note added to document municipality/county source idiosyncrasies, historical backfill planning, and recurring sync strategy
- first source-profile matrix added for `San Rafael` and `Marin County`
- first historical backfill plan added, targeting `2019-01-01` for the initial council, BOS, campaign, and disclosure wave
- first wave-01 source execution completed for `San Rafael City Council meetings`:
  - direct raw HTML capture of the archive page
  - extracted inventory of `263` meeting rows spanning `2019` through `2026`
  - meeting-type classification across `regular`, `special`, `closed_session`, `special_closed_session`, `special_retreat`, `study_session`, and `cancelled`
  - artifact-availability tracking for agenda, packet, minutes, and video tabs
- first narrowed breadth-sprint execution slice completed for `San Rafael City Council 2019+`:
  - added a repeatable council meeting-page capture workflow over the full archive inventory
  - captured raw HTML for all `263` meeting pages referenced by the `2019+` archive
  - extracted direct meeting-page continuity for starts-at time, agenda/packet/minutes/video URLs, and lightweight agenda metadata
  - normalized a citywide council backbone bundle with `263` `Meeting` nodes and `264` `Record` nodes
  - widened graph-v1 import scope to include that council backbone without inventing citywide `Decision` or `VoteCast` objects prematurely
  - made the remaining boundary explicit: citywide agenda-item, decision, and vote extraction is a second pass on the captured meeting pages and linked minutes, not part of the archive-only meeting spine
- second wave-01 source execution completed for `Marin County Board of Supervisors meetings`:
  - direct raw HTML capture of the official Granicus publisher archive at `view_id=33`
  - extracted `317` archived meetings spanning `2019` through `2026`, plus `3` currently listed upcoming events
  - meeting-type classification across `regular`, `budget`, `joint_meeting`, `truth_act_forum`, and `other`
  - artifact-availability tracking for agenda, minutes, video, captions, MP3, and MP4 links
- third wave-01 source execution completed for `Marin County campaign finance`:
  - added a dedicated yearly-export adapter against the public NetFile portal
  - captured amended-only yearly export ZIPs for `2019` through `2026`
  - recorded portal year coverage back to `1997` and current election-tree labels for public election context
  - confirmed the operating split: yearly export is the historical backfill surface, while RSS remains the near-real-time change feed
- fourth wave-01 source execution completed for `San Rafael Form 700`:
  - added a dedicated ASP.NET form-post adapter against the public San Rafael NetFile portal
  - captured a full visible-history `700 filers` export plus the live portal shell
  - extracted `1085` filing rows spanning `2018-07-02` through `2026-04-08`
  - confirmed the wave-01 promotion floor yields `1078` in-scope filings from `2019` forward
  - confirmed the current platform split: the export is strong for mass filing inventory, while direct document URLs are exposed on only `16` rows in the exported HTML
- fifth wave-01 source execution started for `San Rafael city-side campaign filings`:
  - added a discovery-aware election-page capture workflow that starts from the city's own `elections` and `past-elections` index pages
  - added a derived inventory workflow that uses the San Rafael disclosures page plus those discovered election landing pages to enumerate city-side campaign filing destinations
  - captured `13` election landing pages spanning `2010` through `2026`
  - confirmed `9` campaign-bearing election pages: `6` election-level filing-folder pages and `3` candidate-folder pages
  - captured the two top-level Laserfiche filing destinations and `27` candidate-specific child folder IDs across the November 3, 2020, November 8, 2022, and November 5, 2024 election pages
  - extracted cycle-specific independent-expenditure filing folder IDs for `2020` and `2022`
  - confirmed the source-shape breakpoint: the November `2011` through `2018` pages plus the June 7, 2016 page expose election-level campaign filing folders, while `2020+` pages expose candidate-specific filing folders
  - confirmed that the June 8, 2010, November 2, 2010, June 5, 2018 special, and June 2, 2026 special pages are useful election-context records but do not currently expose campaign-filing destinations
  - recorded the current adapter boundary explicitly: anonymous Laserfiche folder-listing probes for both top-level campaign folders and a sampled child folder currently fail with session-limit error `[9030]`
  - confirmed the current working discovery pattern is `elections / past-elections -> election landing page -> campaign filing destination`, with Laserfiche browse probing kept as a secondary experiment rather than the primary discovery path
- selective raw PDF export is now proven for the high-value city-side `Form 460` subset through the public Laserfiche export-job path
  - the schedule extractor now uses that PDF text layer to reconcile itemized `Schedule E` payments for the selected filings
  - added a direct-record follow-on capture workflow for page-linked `DocView` records exposed on the election pages
  - captured `37` unique page-linked election records from the San Rafael election pages
  - fully extracted `36` of those records through the public Laserfiche metadata, document-info, and OCR-text endpoints
  - narrowed the remaining direct-record extraction problem to one holdout: entry `41998` (`Resolution Calling Election` on the June 2, 2026 special-election page)
  - normalized the direct-record slice into a graph-ready election bundle with:
    - `13` page-level election objects spanning `2010` through `2026`
    - `37` record refs tied back to the raw Laserfiche record family
    - `25` council meeting candidates derived from official record metadata
    - `21` conservative election decision candidates for call, results, cancellation, unopposed-appointment, and initiative-submission actions
    - explicit reuse of the existing canonical 2024 seat-specific election objects only where already proven elsewhere
    - an explicit note that entry `41989` already preserves the 2026 call-election resolution text, so entry `41998` is a completeness gap rather than a blocker for the 2026 election chain
  - normalized the page-linked campaign discovery layer into a graph-ready discovery bundle with:
    - `50` record refs spanning the disclosures page, election indices, `9` campaign-bearing election pages, top-level Laserfiche destinations, election-level filing folders, candidate filing folders, IE filing folders, and the repeated IE ordinance record
    - `11` actor candidates covering the unique city-office candidates currently visible in the `2020`, `2022`, and `2024` mayoral and council races
    - `15` discovery-stage candidacy candidates tied to existing San Rafael seat IDs and page-level election IDs
    - an explicit promotion boundary that keeps school-board, city-attorney, and clerk-assessor rows as discovery-only filing-folder records until those institutions and seats have their own canonical layer
  - promoted the discovery layer into real public folder-listing capture and first filing objects:
    - added a repeatable Laserfiche folder-listing adapter for San Rafael campaign folders
    - captured `37` filing-folder listing responses with `33` successful public folder listings and `331` listed document rows
    - confirmed the stronger source boundary: anonymous folder listing is a real public capture path, not just page-linked discovery
    - normalized the city-office subset into `14` candidate-linked committees, `228` filing records, and `14` committee-enriched candidacy records
    - narrowed the remaining gap to direct raw filing-document recovery from the exposed entry ids
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
  - selective city-side `Form 460` OCR capture and first schedule extraction layer:
    - three OCR-backed San Rafael filings promoted from filing-shell records into row-level extraction artifacts
    - first city-side schedule bundle with `103` campaign `MoneyFlow` candidates across contributions, one Schedule D candidate contribution, and high-confidence vendor/payee rows
    - explicit documentation that OCR extraction is usable for joins and recurrence work but still incomplete relative to reported filing totals
  - Marin Resource Recovery sponsor-name drift resolved conservatively in favor of keeping `Marin Resource Recovery` and `Marin Resource Recovery Center` as separate actors
  - Form 803 follow-on slice established around San Rafael behested-payment guidance and filing-surface verification:
    - direct raw captures for the February 5, 2026 City Council governance protocols page/PDF and the January 20, 2026 agenda packet page/PDF
    - verified that the public San Rafael SEI portal is Form 700-oriented and does not visibly expose a Form 803 filing type
    - verified the local-versus-state filing boundary: local officials file Form 803 with the local agency, while FPPC's public Form 803 search is state-level
    - resolved the local filing-surface blocker through the San Rafael public Laserfiche portal
    - captured the first real local Form 803 sample, `Form 803 - Kate Colin`
    - promoted the first local `Filing` plus `MoneyFlow: behested_payment` with payor `Pacific Gas and Electric Company`, payee `Canal Alliance`, amount `$5,000`, date `2025-08-08`, and purpose `Affordable Applications Training`
    - codified the Laserfiche capture path in a repeatable script and confirmed that the broader search census still surfaces only one actual filed local Form 803 as of April 11, 2026
- first canonical identity tranche added:
  - dedicated identity-resolution submodel and worked-example docs
  - first evidence-backed San Rafael canonical seed bundle for city institutions, electeds, and recurring organizations
  - raw councilmember placeholders in earlier bundles now have a documented promotion path into canonical actor IDs instead of staying permanent pseudo-actors
  - role claims for the August 19, 2024 council roster are accepted as identity claims without forcing weak seat or district joins
  - official San Rafael elected-official, City Council, and November 5, 2024 election pages captured as identity evidence
  - explicit seat candidates and current `SeatService` candidates added for the at-large Mayor and Districts 1-4
  - `Vice Mayor` clarified as a role layered on a district seat service rather than a separate elected seat
  - older San Rafael meeting and disclosure bundles backfilled so votes and the first local Form 803 sample now target canonical actor, seat, and `SeatService` IDs
- first real media pressure test added:
  - direct raw JSON capture of the August 24, 2024 Mahon Creek Marin IJ article through the public WordPress post API
  - extracted mention layer preserving article-scoped labels for Rachel Kertz, Katie Fleet, Kevin Bruner, Mark Rivera, and John Stefanski
  - normalized worked example showing one canonical join, two case-scoped joins, and unresolved article-only mentions held in the review layer
  - second direct raw JSON capture of the September 20, 2024 site-preparation Marin IJ article chosen for overlap rather than chronology
  - first recurrence layer showing cross-source recurrence for Mark Shotwell, Mel Burnette, Defense Block Security, and Downtown Streets Team, plus an unresolved repeated Mark Rivera cluster
  - first cross-domain media join layer connecting `Mark Shotwell / Ritter Center` to official program context and `Downtown Streets Team` to official contract, moneyflow, and decision records
  - first media-to-disclosure overlap linking `San Rafael Mayor Kate Colin` in the September 20, 2024 Marin IJ article to her later local Form 803 filing and normalized behested-payment moneyflow, explicitly modeled as identity continuity rather than a causal policy-finance claim
  - first media-to-campaign overlap linking `Rachel Kertz` in the August 24, 2024 Marin IJ article to her public 2024 San Rafael campaign committee, candidacy, and filing trail, explicitly modeled as actor continuity rather than a causal policy-finance claim
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
