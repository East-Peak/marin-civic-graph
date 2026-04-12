# Decision Log

This is the repo-local running index of the highest-signal project decisions.

Use it as the fast recovery layer after compaction or context loss.

Detailed decision writeups still live in:

- `~/.openclaw/workspace/decisions/`

The rule is:

- workspace decision note = detailed rationale
- this file = compact running index
- repo docs = durable technical implementation notes

Backfilled on April 12, 2026 from the existing workspace decision set and project history.

## 2026-04-12

- **Active projects need a repo-local running decision index**
  - Keep a compact `docs/decision-log.md` in the repo, with detailed rationale still living in workspace decisions.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-active-projects-need-repo-local-decision-log.md`

- **Validation checks are first-class review objects**
  - Add `ValidationCheck` to distinguish extraction gaps from source inconsistency.
  - First live use is San Rafael `Form 460` reconciliation and summary-rollup QA.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-validation-check-layer-for-reconciliation-and-anomaly-work.md`

- **V1 graph materialization should use a projection layer and a narrow core scope**
  - Keep the first import to the San Rafael governance spine, include `ValidationCheck`, and leave `Mention` / `Claim` and top-level legal / records tabs out of v1.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-v1-materialization-should-use-a-projection-layer-and-a-narrow-core-scope.md`

- **Graph v1 should materialize from projected JSONL, not directly from bundle-local JSON**
  - Keep the importer boring: build a projection manifest, emit uniform node/edge envelopes, generate Cypher, and let smoke checks prove the core San Rafael spine before widening scope.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-graph-v1-materialization-scaffold-should-center-on-projected-jsonl.md`

- **Graph-v1 evidence completeness can be improved with narrow record bundles instead of widening scope**
  - The right next move after the first projection was not a new ontology tranche. It was a focused campaign-evidence `Record` bundle that promotes OCR, PDF, and folder artifacts already cited by live filings, money flows, and validation checks.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-graph-v1-campaign-evidence-completeness-should-use-a-record-bundle.md`

- **Schedule A QA should anchor on official itemized and unitemized summary totals**
  - Do not compare extracted row sums only to the top-line filing total.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-form460-schedule-a-summary-should-anchor-qa.md`

- **Schedule E should prefer preserved PDF text when the export exists**
  - Use OCR for what it does well, but treat the recovered PDF text layer as stronger evidence for itemized payment extraction.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-form460-schedule-e-should-prefer-pdf-text.md`

- **City-side campaign filings can be recovered through a layered public path**
  - Accept a staged adapter stack of discovery normalization, folder listings, OCR capture, and raw PDF export instead of waiting for one perfect endpoint.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-city-campaign-discovery-normalization.md`
    - `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-city-campaign-folder-listing-surface.md`
    - `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-city-campaign-form460-ocr-path.md`
    - `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-form460-raw-pdf-export-path.md`
    - `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-form460-schedule-extraction-layer.md`

- **Outside-money title records are usable before full schedule extraction**
  - Promote public IE title-layer evidence conservatively rather than blocking on complete amount-level capture.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-city-campaign-ie-title-layer.md`

- **Form 700 backfill uses the NetFile export as the mass-inventory surface**
  - Treat the export as the stable history backbone and direct filing links as a separate recovery problem.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-form700-backfill-surface.md`

- **Vice Mayor is a bounded role claim, not a separate seat**
  - Model it on top of a councilmember `SeatService`.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-vice-mayor-annual-role.md`

## 2026-04-11

- **Campaign and disclosure modeling starts with election, committee, candidacy, filing, and economic-interest disclosure**
  - Keep committees distinct from actors and filings distinct from filing records.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-11-campaign-disclosure-node-set.md`

- **Campaign joins should resolve seat context explicitly and keep sponsor name drift conservative**
  - Promote election and seat context when official evidence supports it, but keep near-identical sponsor names separate unless the public record actually justifies a merge.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-11-campaign-seat-resolution-and-pac-schedule-modeling.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-campaign-sponsor-name-drift-resolution.md`

- **Local Form 803 work uses the city’s public-records surface, not the SEI portal**
  - Treat local behested payments as a distinct filing path and capture workflow.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-11-form-803-local-filing-boundary.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-san-rafael-form-803-public-records-surface.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-form803-repeatable-capture-workflow.md`

- **Canonical identity and elected officeholding need separate layers**
  - Start with identity seeds, then promote explicit `SeatService` objects and backfill older bundles to them.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-11-canonical-identity-seed-layer.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-seatservice-for-elected-officeholding.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-backfill-san-rafael-seatservice-refs.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-san-rafael-d2-d3-seatservice-start-dates.md`

- **Media promotion should move through mention, recurrence, and bounded cross-domain joins**
  - Start with `Mention -> Claim`, then promote recurrence and cross-domain overlap only where the evidence supports it.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-11-first-media-mention-claim-worked-example.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-first-media-recurrence-layer.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-first-media-cross-domain-joins.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-first-media-disclosure-overlap.md`

- **Operations should be source-profile driven, with a 2019+ backfill floor**
  - Capture source quirks explicitly, build source profiles, then run wave-based backfill from stable high-value surfaces.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-11-source-operations-registry.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-first-source-profile-matrix-and-backfill-wave.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-first-wave01-source-execution-san-rafael-council.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-second-wave01-source-execution-marin-bos.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-third-wave01-source-execution-marin-campaign-exports.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-fourth-wave01-source-execution-san-rafael-city-campaign-inventory.md`

- **San Rafael election history needs its own evidence backbone**
  - Use election-index discovery, direct record capture, and normalized election records rather than relying only on city roster pages.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-11-san-rafael-election-index-discovery-backbone.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-san-rafael-election-direct-record-capture.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-san-rafael-election-record-normalization.md`

- **Procurement uses agreement-centered modeling**
  - Keep `Procurement`, `Agreement`, `Amendment`, `Deliverable`, and `PerformanceReview` separate.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-procurement-layer-node-set.md`

- **Proxy captures can later upgrade to direct artifacts without changing semantic identity**
  - Preserve source lineage while keeping `source_id` and `record_id` semantics stable.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-11-proxy-to-direct-artifact-upgrade-rule.md`

- **Downtown Library contract and funding threads must stay split**
  - Separate agreement objects and separate state-funding relationships are required to keep the project honest.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-11-downtown-library-separate-agreement-objects.md`
    - `~/.openclaw/workspace/decisions/2026-04-11-downtown-library-state-funding-split.md`

- **Prime Electric contract amount must stay separate from broader project totals**
  - Preserve contract value, contingency, and related project cost layers distinctly.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-11-prime-electric-contract-vs-project-total.md`

- **Permit/project work needs explicit `Project`, `Application`, `Determination`, `Permit`, `Condition`, and `Appeal` objects**
  - Do not flatten planning threads into one meeting or one page.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-permit-layer-node-set.md`

## 2026-04-10

- **The graph uses stable IDs and explicit provenance**
  - Normalized files are the join layer; Neo4j is a rebuildable materialization, not the source of truth.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-graph-joins-and-identity.md`

- **`Record` is the umbrella evidence node**
  - Articles, ordinances, minutes, packets, contracts, filings, and notices all live under `Record`.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-layered-graph-data-model.md`

- **Open questions must be centralized**
  - High-signal modeling and join ambiguities belong in `docs/open-questions.md`, not scattered only across JSON blobs and chat.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-centralize-open-questions.md`

- **Judicial and oversight work should be pressure-tested through bounded sample baskets**
  - Expand the graph through a small legal/oversight basket before building broad court ingestion.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-judicial-and-oversight-should-start-with-a-pressure-test-basket.md`

- **Criminal justice modeling begins with public case surfaces and event-level facts**
  - Start from proceedings, charges, custody, release, and disposition, not judge scorecards or identity-enrichment hacks.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-10-criminal-justice-modeling-begins-with-public-case-surfaces.md`
    - `~/.openclaw/workspace/decisions/2026-04-10-criminal-case-submodel-node-set.md`
    - `~/.openclaw/workspace/decisions/2026-04-10-criminal-sample-basket-uses-three-public-record-slots.md`
    - `~/.openclaw/workspace/decisions/2026-04-10-first-criminal-sample-selection-stays-operator-only.md`

- **Domain expansion should follow power surfaces, not just document types**
  - Add new tranches around control surfaces like public process, money, litigation, oversight, media, permits, and procurement.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-domain-expansion-should-follow-power-surfaces.md`

- **Permit and case-study work should preserve ambiguity instead of collapsing it**
  - The first permit basket, the P4134 appeal-chain split, and child-record proxy captures all keep role drift and source mismatch explicit.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-10-first-permit-sample-basket.md`
    - `~/.openclaw/workspace/decisions/2026-04-10-first-permit-execution-slice.md`
    - `~/.openclaw/workspace/decisions/2026-04-10-p4134-appeal-chain-split.md`
    - `~/.openclaw/workspace/decisions/2026-04-10-p4134-child-record-proxy-capture.md`
