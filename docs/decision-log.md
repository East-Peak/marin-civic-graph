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

## 2026-04-13

- **The first Ralph-loop batch can stop once the query-pack gate is met**
  - Batch `01` of `san-rafael-city-campaign-money-01` hardened the city-side Form `460` OCR/PDF workflows into manifest-driven batch tools, recovered a thin but sufficient `2020` QA-backed money layer, and moved the fixed query pack to `5/5` passing.
  - The same batch also exposed a validation-noise problem on sparse older filings, so the schedule extractor was tightened to suppress zero-information checks with no real reference value before the batch was accepted.
  - Once the gate is met, later batches become optional review decisions, not automatic next steps. `2022` stays available, but it is now `deferred_pending_review` rather than the default next move.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-13-first-ralph-loop-batch-can-stop-on-query-pack-success.md`

## 2026-04-12

- **Breadth execution should now use bounded Ralph loops instead of undifferentiated backfill**
  - Once the fixed query pack exists, widening should run through one lane-scoped batch loop at a time: select a bounded batch, capture, extract, normalize, rebuild `graph-v1`, rerun the fixed query pack, and accept the batch only if the graph improved in the target lane.
  - The first active loop is `san-rafael-city-campaign-money-01`, aimed at turning `Q4` from fail to pass by adding multi-cycle QA-backed city-office campaign money while keeping noisy OCR actors out of graph-v1.
  - Durable control files now live in `registry/loop-manifests/`, with the current loop manifest at `registry/loop-manifests/san-rafael-city-campaign-money-01.json`.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-breadth-execution-should-use-bounded-ralph-loops.md`

- **The fixed five-query pack now gates breadth-sprint decisions**
  - Run the checkpoint against the projected `graph-v1` payload, not just a live Neo4j session, so the sprint can be judged consistently from repo state alone.
  - The first formal run now passes `Q1`, `Q2`, `Q3`, and `Q5`, while `Q4` still fails because the San Rafael campaign money layer has QA-backed recurrence only in `2024`.
  - That means the next highest-leverage breadth move is still the San Rafael city-office campaign filing backbone, but specifically the multi-cycle QA-backed money path rather than county widening or more schema work.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-fixed-query-pack-should-gate-breadth-sprint-checkpoints.md`

- **The first legal bundle should start with one local case and one court-origin order**
  - `legal-precedent-01` starts with `Boyd v. City of San Rafael`, then grows by adding the TRO and preliminary-injunction orders as strong public filed-order copies while keeping the same normalized case spine.
  - Keep the bundle normalized and durable now, but do not widen graph-v1 import scope until the legal lane has stronger provenance and broader comparison coverage.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-12-first-normalized-boyd-legal-bundle.md`
    - `~/.openclaw/workspace/decisions/2026-04-12-boyd-injunction-orders-can-start-as-public-filed-order-copies.md`

- **The legal lane should widen from Boyd to one official controlling-precedent bundle before import**
  - `legal-precedent-02` adds `City of Grants Pass v. Johnson` as the first external controlling-precedent bundle, anchored on the official Supreme Court docket and slip opinion plus official San Rafael and San Francisco response records.
  - Keep the legal lane normalized-only for now; the next real gap is lower-court chain depth, not whether the controlling precedent record exists.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-grants-pass-should-enter-the-legal-lane-as-an-official-precedent-bundle.md`

- **The Grants Pass lower-court chain should stay inside `legal-precedent-02` as separate related cases**
  - Keep the District of Oregon phase, the Ninth Circuit phase, and the Supreme Court phase in one precedent bundle, but preserve them as separate `Case` objects connected by lineage rather than flattening them into one docket identity.
  - Treat the district opinion and judgment as strong public filed-order copies, the Ninth Circuit amended opinion as official court-origin, and the remaining gap as supporting-provenance completeness rather than core precedent absence.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-grants-pass-lower-court-chain-should-live-inside-legal-precedent-02.md`

- **The next phase should be a controlled breadth sprint, but narrowed to the dense San Rafael loop first**
  - Freeze schema by default and judge success by query density rather than by how many new files appear.
  - After adversarial review, narrow the first breadth phase to:
    - San Rafael City Council `2019+`
    - San Rafael Form `803` plus elected-officeholder Form `700`
    - San Rafael city-office campaign filing backbone
  - Keep Marin County BOS and broad Marin County campaign finance out of the first phase unless the city-side query checkpoint proves the graph still needs them next.
  - Detailed notes:
    - `~/.openclaw/workspace/decisions/2026-04-12-next-phase-should-be-a-controlled-breadth-sprint.md`
    - `~/.openclaw/workspace/decisions/2026-04-12-controlled-breadth-sprint-should-be-san-rafael-first-and-join-density-led.md`

- **The first breadth-sprint execution slice should start with a meeting-page-backed council spine**
  - Capture the full San Rafael City Council `2019+` meeting-page layer and promote `Meeting` plus `Record` nodes first.
  - Do not pretend the citywide decision timeline is solved yet; agenda-item, decision, and vote extraction remain a second pass on the captured meeting pages and linked minutes.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-council-breadth-slice-should-start-with-meeting-page-backed-meeting-and-record-nodes.md`

- **The elected-disclosure breadth slice should stay narrow and current-service-backed**
  - Use the San Rafael Form `700` export as the evidence surface, but only promote filings that resolve cleanly to current canonical officeholders and explicit current `SeatService` start dates.
  - Defer pre-current-term rows and broad staff / commission disclosure import until older seat-service lineage is modeled.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-form700-officeholder-continuity-should-stay-narrow.md`

- **The second San Rafael council breadth pass should be minutes-backed and consent-conservative**
  - Capture the linked minutes PDFs citywide, promote minutes `Record` nodes, and extract `AgendaItem` plus `Decision` objects from those minutes rather than inventing decisions from archive metadata.
  - For consent blocks, attach one section-level voted decision and link subitem outcomes back to it instead of fabricating standalone roll calls for every consent subitem.
  - Skip generic minutes-derived decisions for meetings already covered by deeper San Rafael bundles, including the August 19, 2024 homelessness package and the page-backed election-record meetings.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-council-decision-breadth-pass-should-be-minutes-backed-and-consent-conservative.md`

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

- **Graph-v1 should use narrow actor and issue supplements before broader canonical expansion**
  - Promote only the strongest campaign actors and canonical issues needed to close obvious graph-v1 gaps. Leave OCR-tainted, platform-like, and alias-heavy actors out of the core import until the identity layer is stronger.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-graph-v1-should-use-narrow-actor-and-issue-supplements-before-broader-canonical-expansion.md`

- **The first live local Neo4j load should follow projection smoke checks, not replace them**
  - Keep the projected JSONL layer and smoke checks as the gate, then run a real local load/query pass to prove the graph is actually usable before widening scope.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-first-live-local-neo4j-load-should-follow-projection-smoke-checks.md`

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
