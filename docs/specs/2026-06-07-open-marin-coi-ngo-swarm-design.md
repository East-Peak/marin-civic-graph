# Open Marin — COI/NGO Legibility Swarm: Design Spec

**Date:** 2026-06-07
**Status:** Draft — Codex rounds 1–3 + live-AuraDB verification + consolidation decision applied; **design converged** (round 3 found zero P0s; only precision items, all applied)
**Author:** Claude (Opus 4.8 1M), with Stuart Watson
**Builds on:** The live v2 graph (typing via `scripts/canonical_type.py` / `app/src/lib/canonical-type.ts`; loaded by `scripts/load_neo4j_v2.py`; post-processed by `scripts/refresh_openmarin.py`).

**Rebuild posture:** The AuraDB instance is a **rebuildable materialization**, not the source of truth — the normalized bundles + ingest scripts are. Nothing in the running instance is load-bearing. This spec **evolves the schema to the clean target shape and rebuilds from source.**

> **Targeting note (verified against the running DB, 2026-06):** The live AuraDB contains `Person` (6,305), `Organization` (1,346) with subtype labels (`Nonprofit`, `Business`, `Government`, `Political`) — **no `Actor`/`Institution`**. Form 700 disclosures are `Filing` nodes (10,047), **not** an `EconomicInterestDisclosure` type. Case involvement is the `PARTY_TO` relationship, **not** a `CaseParticipation` node. The current rebuild reaches that schema via a **two-stage path** — `build_graph_projection.py` (emits intermediate `Actor`/`Institution`) → `migrate_graph_v2.py` (→ `Person`/`Organization`) → `load_neo4j_v2.py` — plus direct-to-v2 ingestors (e.g. `ingest_form700.py --load`). That intermediate `Actor`/`Institution` representation is what misled two review rounds; **Phase 0 removes it** (§2.5).

---

## 1. Purpose & Thesis

Open Marin already makes local government *process* legible. This spec extends it to make **money and influence** legible — to answer one durable question:

> **For any actor consuming public resources, who funds them, what influence do they exert, and who are they accountable to?**

The motivating cases are concrete: NGOs that draw large taxpayer revenue while their principals donate to the officials who approve it; individuals who present as unaffiliated "concerned residents" in media or public comment while actually funding litigation or organizations on the same issue; nonprofits whose governance overlaps the boards that fund them. The goal is **legibility, not accusation.** The graph surfaces fully-sourced structure; the reader draws the conclusion.

This reframes the north star from the v1 thread-centric pressure comparison (QX-001) toward an **actor- and organization-centric legibility lens.**

### Two load-bearing principles (see §7)

1. **Provable structure, never imputed motive.** The graph asserts only what primary records support. It never asserts intent, corruption, or coordination — those require FOIA/field reporting that is out of scope.
2. **Scrutiny points up the power gradient.** Subjects are organizations, officials, and funders consuming public resources. The system does **not** model, track, profile, or *externally process* (e.g. embed) vulnerable individuals (migrants, unhoused people, minors). Ethical floor and legal-defensibility floor at once.

---

## 2. Settled design decisions

| Fork | Decision |
|------|----------|
| **Anchor** | Converged: the tedious cleanup/normalization passes **are** the COI substrate. One pipeline. |
| **Mechanism** | An autonomous **agent swarm** does the research and assembles the evidence; Stuart consumes results by querying through Claude. |
| **Autonomy line** | **Gather + link, judgment gated.** The swarm captures, extracts, resolves (with confidence), links, ranks. Ambiguous merges → review queue, never silent. COI candidates are evidence bundles a human adjudicates. |
| **First-pass scope** | **Go wide immediately**, refined to **thin-wide-then-deep**: cheap high-signal layer across all jurisdictions first; expensive deep extraction only on hot candidates. |
| **Orchestration** | **Goal-loop swarm backbone** — manifest-governed, checkpoint-gated, cron-durable on the always-on Mac mini. In-session, a Workflow may parallelize a batch. DigitalOcean is escalation only. |
| **Foundation** | **v2-native projection consolidation first** (Phase 0) — one schema, no intermediate, before COI. |

### 2.5 Build sequence (phased; each phase TDD'd + Codex-gated)

The DB isn't precious, so "do it right" means clean foundations before the COI layer. The deepest defect surfaced during design was a **two-headed schema**: the bulk rebuild emits an intermediate `Actor`/`Institution` representation that is then migrated to `Person`/`Organization`. That intermediate misled two review rounds. Phase 0 eliminates it.

- **Phase 0 — v2-native projection (foundation, first).** Build a projection that emits the settled `Person`/`Organization` schema **directly from the normalized bundles**, collapsing the migration step. Retire `build_graph_projection.py` + `migrate_graph_v2.py`; reconcile/replace the stale `registry/neo4j-schema.cypher`; make `canonical_type.py` (+ TS twin) the undisputed source of truth. **Inputs are a `v2 materialization manifest`** — the normalized bundles **plus the settled direct-to-v2 ingestor outputs** (e.g. `ingest_form700.py` JSONL), since not all live facts come from the bundle projection. **Acceptance:** a full rebuild from that manifest passes `verify_neo4j_v2.py` + the query pack and is **equivalent over canonical *fact* nodes/labels/edges/relationship-props** — *excluding* regenerated derived state (search props, embeddings, UMAP, clusters, `_SyncState`), which is rebuilt by `refresh_openmarin.py`, not diffed. No new COI types yet.
- **Phase 1 — Clean COI schema (§4):** `Membership`, `EconomicInterest` (graph nodes); `Mention`/`Claim` into core (outbound-ineligible); `ResolutionCandidate`/`PatternCandidate` as sidecar review-queue artifacts. Each new graph type passes the §4.6 parity checklist.
- **Phase 2 — Swarm pipeline (§6):** capture→extract→resolve→link→rank + the goal-loop manifest.
- **Phase 3 — Patterns + NGO Legibility Dossier (§5).**

Working ingestors (`ingest_form700.py`, the 7 adapters) are **kept and extended**, not rewritten. Only the v1 projection + migration are retired.

---

## 3. Readiness assessment (verified against the live v2 DB)

**Ready:** the 21-type ontology is live via `canonical_type.py`; capture is built (7 adapters + dedicated ingestors); `load_neo4j_v2.py` is a generic batched node/edge loader; `ValidationCheck` + the reconciliation model are the gate substrate; 22 `SAME_AS` edges + canonical seeds mean resolution is partially live; `refresh_openmarin.py` republishes to the app.

**Not ready (the §4 work):** `Membership` (0), `EconomicInterest` (new), Form 700 *interiors* (only filing-level today), `Mention`/`Claim` (0 — not in core), `Nonprofit` identification (only **4** orgs labeled), 990/registry/USASpending sources (none). And the foundation (§2.5 Phase 0) — the two-headed projection.

---

## 4. Section A — Data-model additions (the COI substrate)

New **graph node types** register via the §4.6 parity checklist and load through `load_neo4j_v2.py`. Review-queue objects (§4.3, §4.5) are **sidecar artifacts, not graph nodes.**

### 4.1 Reify `Membership` as a node

`Membership` is defined in `docs/graph-data-model.md:593` as a **temporal object**, and the model says *"board service should be a `Membership`, not just `actor MEMBER_OF actor`"* (line 1067). Unbuilt (0 nodes). Build as a **node** (prefix `membership-`): `person_id`, `organization_id`, `role`, `started_at?`, `ended_at?`, `confidence`, `source_basis`, `evidence_record_ids[]`. Edges `MEMBER`→`Person`, `MEMBER_OF_ORG`→`Organization`; optional derived `CURRENT_MEMBER_OF`. Reifying lets multiple roles/date-windows/evidence coexist without edge-dedup collapse (see §4.7). Precondition for P1, P3, P6.

### 4.2 New `EconomicInterest` node + a real interiors pipeline

The graph knows a Form 700 `Filing` exists but not *what it discloses*. `ingest_form700.py` only parses the NetFile index rows — it does **not** fetch/OCR the schedule documents. So this is a **new capture+extract pipeline**, `extract_form700_interiors.py` (mirroring the existing Form 460 OCR scripts: capture → OCR → schedule parse → reconcile), not a small extension.

- **`EconomicInterest`** node (prefix `economicinterest-`): `interest_type` (income source, investment, real property, business position / board seat, gift, loan, travel), `counterparty_name_raw` (always preserved), `amount_band`, `position?`, `confidence`, `evidence_record_ids[]`.
- Edges: `DISCLOSED_AS` (`Filing` → `EconomicInterest`); `INTEREST_IN` (`EconomicInterest` → `Organization`|`Person`|`Place`) **emitted only when the counterparty resolves above threshold** — otherwise the raw name stays on `counterparty_name_raw` + a `ResolutionCandidate` (§4.3); no edge to an unresolved stub.
- Reconciliation (extracted interests vs. disclosed schedule) emits `ValidationCheck`. Golden-fixture tests required.

Precondition for P2.

### 4.3 Cross-namespace resolver — conservative; candidates are sidecar artifacts

`person-*` identities don't fully reconcile, and `docs/identity-resolution-submodel.md` refuses name-similarity merges. The resolver:

- **Auto-merges only on deterministic signals** — exact same-record identity, shared EIN, exact legal-identifier — writing a `SAME_AS` edge (the existing mechanism, 22 live).
- **Every non-deterministic join becomes a `ResolutionCandidate`** — a **sidecar review-queue artifact** (JSON read-model, *not* a graph node, *not* in `ALL_TYPES`): `subject_ref`, `candidate_ref`, `signals[]`, `confidence`, `status` (`queued`/`approved`/`rejected`), `evidence_record_ids[]`. On approval, the resolver writes the `SAME_AS` (reversible); name similarity alone never merges. Queue growth is a stop condition (§6).

### 4.4 New sources: 990 / nonprofit registry + government-spending feeds

First new external sources, feeding `Organization` enrichment and `Membership`: **IRS Form 990** (ProPublica Nonprofit Explorer / IRS bulk: EIN, officers → `Membership`, annual revenue / gov-grant figures); **CA RCT + SOS** (legal-entity resolution, agents, status); **USASpending + state portals** (federal/state pass-through; **enrichment-only until recipient→`Organization` resolution is reviewed**). `Organization` gains additive identity fields (`ein?`, `legal_name?`, `nonprofit_status?`, `registry_ids[]`). **Annual fiscal facts are year-scoped, evidence-backed `Filing`/metric records — never flattened onto the Org node** (so dossiers label the year, never imply currency). This also expands `Nonprofit` labeling beyond today's 4.

### 4.5 COI is a sidecar `PatternCandidate` — never a graph node, never a charged label

The graph holds **facts only** (`Membership`, `EconomicInterest`, `MoneyFlow`, votes, `PARTY_TO`, and — Phase 1 — `Mention`/`Claim`). A "conflict" is **not** a graph node/edge/label. It materializes as a neutral **`PatternCandidate`** — a **sidecar review-queue/read-model artifact** (JSON, *not* in `ALL_TYPES`): `pattern_id` (P1–P6), `subject_refs[]`, `evidence_record_ids[]`, `dependency_refs[]` (the `ResolutionCandidate`s it rests on), `score`, `coverage`, `status` (`queued`/`confirmed`/`dismissed`), `reviewer_outcome?`. Charged descriptors ("pay-to-play," "under-recused," "astroturf") are **pattern names in this spec only** — never in generated artifacts. The artifact presents the neutral evidence bundle; the human supplies the conclusion. (Keeping candidates as sidecar artifacts also keeps them out of `ALL_TYPES`, so they're never embedded/egressed — see §4.6.)

### 4.6 New-graph-type parity checklist (Phase 1 gate)

Adding a node type is **not** "register in `canonical_type.py` + load." Each new graph type (`Membership`, `EconomicInterest`, `Mention`, `Claim`) must land across **every** surface or it won't search/display/expand/typecheck:

- `canonical_type.py` `ALL_TYPES` + `TYPE_BY_ID_PREFIX`, **and** the TS twin `app/src/lib/canonical-type.ts` + `type-display.ts` `NodeType`
- v2 schema constraints + search/fulltext indexes (replacing the stale `neo4j-schema.cypher`)
- search-property builders, catalog counts, explorer expand-quotas
- the app's exhaustive `NodeType` surfaces — id aliases, display names, `entity-facts.ts`, `entity-temporal.ts`, `explorer-queries.ts` sub-specs, sprite/style maps, catalog grouping — ideally guarded by a **generated parity test** so a missing surface fails CI rather than silently breaking the explorer
- **`outbound_policy.py` — end-to-end, not just embeddings:** `Mention`/`Claim` default **outbound-ineligible**, and **every external stage filters through `outbound_policy.is_eligible`** — Voyage embedding, Anthropic cluster-naming (`name_clusters.py`), and constellation publish (`publish_constellation.py`). Pending/canonical constellation fields are **cleared** for ineligible types (a stale `pending` field must not leak). `Membership`/`EconomicInterest` eligibility set deliberately.
- **egress negative tests at all three points** proving `Mention`/`Claim` (and the sidecar queues) never reach Voyage, Anthropic naming, or a published constellation payload

### 4.7 Relationship identity

`load_neo4j_v2.py` dedups edges by `(source, type, target)`, so a single triple holds one edge — adding "a relationship key" is inert unless the loader changes. **Default rule: every repeatable, property-bearing relationship is reified as a node** (`Membership`, `EconomicInterest` already are). A keyed edge is allowed only as a deliberate exception, and then requires both an edge-envelope `relationship_id`/`identity_key` **and** a corresponding keyed-`MERGE` change in `load_neo4j_v2.py`; tests assert no silent collapse either way.

---

## 5. Section B — COI patterns + the NGO Legibility Dossier

Each pattern materializes as a neutral sidecar `PatternCandidate` (§4.5). Every row links to primary-source `Record`s. A candidate depending on a `queued` `ResolutionCandidate` is itself **withheld** (`queued`). Each pattern carries **its own scoring gate** — capped money bands, an explicit time window, an evidence-independence rule, and a confidence/coverage floor — so a dollar-heavy but weakly-linked candidate can't outrank a legally-cleaner one.

| ID | Pattern | Structure caught | Evidence bundle | Notes |
|----|---------|------------------|-----------------|-------|
| **P1** | Pay-to-play around a vote | Org gets a contract/grant **and** its principals or the org donated to the officials who approved it | Agreement + Decision + votes + contributions + Membership | High |
| **P2** | Under-recused interest | Official discloses an `EconomicInterest` in an org **and** voted on a Decision benefiting it, **no recusal found in the checked records** | EconomicInterest + Decision + vote + benefit + recusal-coverage | **Highest** — needs a **recusal extractor**; absence is reported as "no recusal found in checked records (coverage: …)", never asserted as non-recusal |
| **P3** | Board interlock / revolving door | Same person holds an org `Membership` **and** holds/held office, **and** the org draws public money | Membership + SeatService + org gov money + date overlap | High |
| **P4** | Taxpayer-funded advocacy / pass-through | Org draws a large gov revenue share (year-scoped) **and** spends on political/advocacy activity | 990 gov-grant facts + inbound gov money + outbound campaign money | Highest evidence bar |
| **P5** | Recurring-counterparty cluster | Same org/vendor recurs across many decisions/programs | Cross-domain recurrence (extends QX-004) | Context, not a finding |
| **P6** | Source-framing / context discrepancy *(was "astroturf")* | A subject recurs in media or public comment framed as grassroots/unaffiliated **while** being a funder, litigant, board member, or contractor on the same issue | Media `Mention`/`Claim` recurrence + `PARTY_TO` + MoneyFlow + Membership | Subject eligibility is **machine-enforced** (§5.2), not prose |

**Weighting (per Stuart):** P2, P6, P3 heaviest; P4 highest evidence bar.

### 5.1 Deliberate reversal: `Mention`/`Claim` enter the core graph

v1 *intentionally* kept `Mention`/`Claim` out of core. P6 needs media recurrence, so Phase 1 **reverses that** — safely, because (a) the DB is rebuildable (no migration risk), (b) the conservative promotion rules hold unchanged (media→actor stays a `Claim` until corroborated by an official record, `docs/media-attribution-rules.md`; an uncorroborated media "resident" is never promoted to a `Person`), and (c) `Mention`/`Claim` are **outbound-ineligible** (§4.6) — their text is never embedded or sent to any external service. The reversal trades v1's blanket exclusion for a narrower, enforced conservatism.

### 5.2 P6 subject eligibility is machine-enforced

P6 eligibility is a single named predicate **`is_p6_eligible(subject)`** — a Cypher contract, not prose — so every implementer shares one inclusion boundary. A subject is eligible **only if** at least one of these holds, with explicit edge direction and **approved-`SAME_AS`-only** identity expansion:

- `Organization` (any subtype); or
- **official** — `(:Person)-[:HELD_BY]-(:SeatService)` (or its settled equivalent); or
- **funder** — `(:Person|:Organization)-[:FROM_SOURCE]->(:MoneyFlow)` whose `flow_type` is a campaign/contribution type; or
- **contractor** — `(:Organization|:Person)-[:COUNTERPARTY_ACTOR]-(:Agreement)`; or
- **legal entity** — `(:Person|:Organization)-[:PARTY_TO]-(:Case)`.

A subject reachable *only* as a `Claim`/`Mention` (resident/parent/unhoused/commenter) is **excluded**. Negative tests pin the boundary: a Claim-only resident is excluded; a named resident who later donates/sues/comments is included **only** via the funder/legal leg of the predicate, never by media recurrence alone.

### The NGO Legibility Dossier (flagship output)

For any organization consuming public resources, a one-page, fully-sourced profile: **Funding in** (gov contracts/grants — city, county, state, federal pass-through — with amounts, fiscal year, authorizing decisions); **Influence out** (campaign contributions, media footprint, public-comment mobilization, litigation `PARTY_TO`, lobbying); **Accountability** (legal entity + EIN, year-scoped 990 revenue and gov-revenue share, principals/board via `Membership`, board overlaps with officials); **Provenance** (every line → a `Record`; every disclosure labels its year).

---

## 6. Section C — The swarm pipeline (goal-loop)

Each iteration runs one **bounded lane** through six stages:

1. **Capture** — adapter/ingestor pulls the source (campaign filings, **Form 700 interior documents**, contracts, minutes, 990s, USASpending) → `data/raw/`.
2. **Extract** — parse to structured rows: Form 460 schedules, **Form 700 interiors → `EconomicInterest`** (new `extract_form700_interiors.py`), contract counterparties, named public-comment speakers. Emits `ValidationCheck`.
3. **Resolve** — §4.3: deterministic auto-`SAME_AS`; else `ResolutionCandidate` (sidecar queue).
4. **Link** — emit v2-native nodes + edges, load via `load_neo4j_v2.py`: `Membership`, `DISCLOSED_AS`, `INTEREST_IN` (post-resolution only), money→decision, `Mention`/`Claim`.
5. **Rank** — compute patterns + dossier as sidecar `PatternCandidate`s with per-pattern gates; withhold any resting on a `queued` resolution.
6. **Publish** — run `refresh_openmarin.py`.

**Governance lives in the manifest** (`registry/loop-manifests/*.json`), with **typed numeric fields + an enforcement script** (current manifests store stop-conditions as prose strings — insufficient for an unattended loop):

- **Scope:** thin-wide-then-deep.
- **Guardrails:** deterministic-only auto-merge; no motive assertions; no charged labels in artifacts; scrutiny up-not-down; vulnerable-individual text outbound-ineligible; no schema change without review.
- **Stop conditions (typed, per lane, enforced):** `review_queue_ratio` (queued ÷ confirmed links) `> 0.5`; `validation_fail_growth > confirmed_link_growth` over a 2-batch window; `noisy_actor_count > 0`; an **unplanned** schema need. (Schema evolution is deliberate/reviewed in Phases 0–1, then rebuilds; the autonomous loop never invents schema — it halts for review.)
- **Acceptance gates:** the query pack + `verify_neo4j_v2.py` stay green; every new edge carries provenance; the dossier for a touched org reconciles.

**Durability:** overnight via cron on the always-on Mac mini; each iteration is one checkpointed, resumable batch. A Workflow may parallelize a single in-session batch.

---

## 7. Guardrails & ethics (load-bearing)

1. **Provable structure, never imputed motive.** No artifact asserts intent/corruption/coordination. Incentive, media-coordination, and individual-status allegations are out of scope.
2. **Scrutiny up the power gradient.** Subjects are organizations, officials, funders. Vulnerable individuals are never modeled, profiled, **or externally processed** — `Mention`/`Claim` and all review queues are outbound-ineligible (§4.6); a media "resident" stays an unpromoted `Claim` and is never a P6 subject (§5.2).
3. **No charged labels in artifacts.** Pattern names are internal; output is the neutral evidence bundle.
4. **Gated judgment.** The swarm never publishes a conclusion; every candidate is adjudicated on demand.
5. **Conservative resolution.** Deterministic-only auto-merge; ambiguity → review queue.
6. **Defensibility.** Every surfaced fact is primary-source-linked; every conclusion is left to the reader.

---

## 8. Testing (TDD — required)

Against the **v2-native** pipeline:

- **Phase 0:** a rebuild from the v2 materialization manifest (bundles + settled direct-ingestor outputs) is equivalent to today's graph over **canonical fact nodes/labels/edges/relationship-props** (derived state excluded); `verify_neo4j_v2.py` + query pack green; the retired v1 scripts have no remaining importers.
- **Extractors:** golden-file tests for Form 700 interior parsing; reconciliation emits `ValidationCheck`.
- **Resolver (negative tests are the point):** two distinct same-named people never auto-merge; a non-deterministic match produces a `ResolutionCandidate`, not a `SAME_AS`.
- **Linker:** `INTEREST_IN` never emitted to an unresolved counterparty; new nodes load with provenance; the §4.6 parity surfaces resolve; relationship-key tests assert no silent edge collapse (§4.7).
- **Pattern candidates:** each pattern produces the expected bundle with its gate; a candidate resting on a `queued` resolution is **withheld**; no charged label appears in any artifact; **P6 eligibility edge cases** (resident-who-donates/sues/comments) evaluate against the §5.2 predicate.
- **Egress/eligibility:** assert `Mention`/`Claim`/`ResolutionCandidate`/`PatternCandidate` are never embedded or sent to any external service.
- **Guardrail:** no "conflict" graph label is ever written.

---

## 9. Success criteria

- **Phase 0:** a single v2-native projection rebuilds the graph from bundles, equivalent to today's; `build_graph_projection.py`/`migrate_graph_v2.py` retired; `canonical_type.py` is the sole schema source.
- The §4 additions land on the consolidated pipeline; query pack + `verify_neo4j_v2.py` green.
- Form 700 interiors extracted + reconciled for ≥ the San Rafael officeholder set, with `ValidationCheck` coverage.
- The resolver produces deterministic `SAME_AS` + a populated, auditable `ResolutionCandidate` queue — **zero non-deterministic silent merges** (negative tests).
- ≥1 NGO Legibility Dossier and ≥1 each of P1–P3 and P6 as neutral `PatternCandidate`s, every row primary-source-linked.
- The goal-loop runs unattended overnight, checkpoints, and respects all typed stop conditions.
- Stuart can ask Claude a legibility question and get a sourced answer.

## 10. Out of scope / non-goals

- Motive/intent/coordination/corruption assertions; charged labels in artifacts.
- Modeling, profiling, **or externally processing** vulnerable individuals.
- FOIA, field reporting, non-public data.
- Re-architecting working ingestors or the 21-type core beyond what COI needs (Phase 0 consolidates the projection only; it does not rewrite ingestors).
- A public-facing UI for these findings (separate session).
- DigitalOcean / remote compute (escalation only).
- Partisan scorecards or black-box influence scores.

## 11. Open questions

1. **Resolver corroboration set + thresholds** — exact deterministic signals vs. queued; confidence cutoff. Tune on San Rafael first.
2. **Public-comment speaker extraction fidelity** across the 11 parsers; where weak, P6's public-comment leg stays media/legal-only.
3. **Media promotion bar** — the exact corroboration for promoting a `Claim` to a P6-eligible actor (reuses `media-attribution-rules.md`).
4. **990 + USASpending recipient resolution** — recipient-name → `Organization`; starts enrichment-only with a review lane.
5. **Phase 0 equivalence diff** — the manifest + canonical-fact diff boundary is defined (§2.5/§8); the remaining detail is the exact field-level comparison and tolerance for known-noisy props, settled at implementation.
6. **Goal-loop vs. Workflow split** — confirm `/goal` + cron is the durable backbone and Workflow is in-session-only, when we author the prompt.

---

## Appendix — Codex review log

**Round 1 (2026-06-07, gpt-5.5 xhigh) + live-AuraDB verification — 13 findings (4 P0 / 7 P1 / 2 P2).** All applied. Headline **P0#1** (legacy Actor/Institution; "additive" false) was *right instinct, wrong remedy*: empirical DB check showed the live graph is already `Person`/`Organization` — the v1 projection is a stale intermediate. Bonus corrections: disclosures are `Filing`; case involvement is `PARTY_TO`. P1#5 (edges can't carry props) resolved by the generic v2 loader. Others: reify `Membership` (§4.1); deterministic-only resolver (§4.3); neutral candidate, no charged labels (§4.5); `EconomicInterest` fully specified (§4.2); unresolved counterparty = raw string + candidate (§4.2); recusal extractor (§5/P2); P6 renamed + vulnerable exclusion (§5.2/§7); 990 year-scoped (§4.4); per-pattern gates (§5); numeric stop conditions (§6).

**Post-round-1 constraint change (Stuart):** AuraDB confirmed non-load-bearing → spec retargeted from "strictly additive" to "evolve + rebuild," adding §2.5 phasing and the §5.1 `Mention`/`Claim`-into-core reversal.

**Round 2 (2026-06-07, gpt-5.5 xhigh) — 8 findings (2 P0 / 5 P1 / 1 P2), converging.** All applied. **P0#1:** the v1 projection is a *live* bulk stage, so "retire it" required building a **v2-native projection first** — adopted as Phase 0 (§2.5; Stuart chose full consolidation). **P0#2:** `Mention`/`Claim`/queues in `ALL_TYPES` would be embedded/egressed → made `Mention`/`Claim` outbound-ineligible and `ResolutionCandidate`/`PatternCandidate` **sidecar artifacts, not graph nodes** (§4.5, §4.6) — which also resolved **P1#4** (the core-vs-read-model contradiction). **P1#3:** new-type parity checklist (§4.6). **P1#5:** typed manifest stop-conditions + enforcement (§6). **P1#6:** Form 700 interiors are a new capture pipeline, not an extension (§4.2). **P1#7:** P6 eligibility machine-enforced (§5.2). **P2#8:** relationship-identity note (§4.7).

**Round 3 (2026-06-07, gpt-5.5 xhigh) — convergence check: 0 P0 / 3 P1 / 2 P2, all precision.** No design flaws; design is stable. All applied. **P1-a:** Phase 0 acceptance redefined around a **v2 materialization manifest** + a canonical-fact diff boundary excluding derived state (§2.5/§8). **P1-b:** outbound-ineligibility enforced **end-to-end** — `is_eligible` filtering at embedding, Anthropic cluster-naming, and constellation publish, with pending-field clearing + negative tests at all three (§4.6/§7). **P1-c:** P6 eligibility specified as a named `is_p6_eligible` Cypher predicate with edge directions + approved-`SAME_AS` expansion (§5.2). **P2-d:** relationship-identity made decisive — reify by default; keyed edges require a loader change (§4.7). **P2-e:** parity checklist extended to the app's hardcoded `NodeType` surfaces + a generated parity test (§4.6). **Verdict: converged for a design spec** — remaining items in §11 are implementation-tuning for the plan.
