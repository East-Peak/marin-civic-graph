# Public product + serving substrate — integrated design

**Date:** 2026-07-07 · **Author:** Claude (Fable 5), full public-app read (~6k lines serving layer +
explorer + components) · **Status:** DRAFT — pending Codex adversarial review + Stuart go/no-go.
**Prior art:** substrate debate (2026-07-07, 8-vector Codex review, scratchpad `substrate-debate.md`)
whose five hard gates this spec discharges.

## 0. Goals

1. **Durability**: the public site must not depend on Stuart's Mac mini or a live database to stay up.
2. **Cost**: Aura cancelled; steady-state infra = Vercel (already paid) + ~$0.
3. **Product**: ship the identity dividend + close the exploration underleverage — features land ON
   the new substrate, not against Aura (no new migration debt).

## 1. What exists (read findings)

Seven serving surfaces, all Cypher-at-request-time today:

| Surface | Shape | Port difficulty |
|---|---|---|
| `/api/data` (10 predefined queries) | parameterized Cypher templates | LOW — all SQL-able (debate vector a) |
| `/api/browse/[type]` | typed pagination + substring search | LOW — exact parity feasible |
| `/api/search` + `/search` | Lucene fulltext, 3-bucket contract, score×100+rank | MEDIUM — ranking is a product contract |
| Entity pages (`loadEntity`) | must-show UNIONs + Phase-2 quota fill + edges + neighbor-total | MEDIUM — deterministic but graph-shaped |
| `/api/expand` | 1..4-hop quota-ranked traversal | MEDIUM-HIGH — the explorer's engine |
| `/api/path` | APOC allSimplePaths + **pure-TS scoring** (already!) | MEDIUM — only enumeration is APOC |
| `/` + `/api/status` | live counts + ingest timestamp | TRIVIAL — build manifest |

Key structural facts:
- **Edge semantics are already centralized** (`edge-vocabulary.ts` mirroring `edge_vocabulary.py`;
  PHASE2_WHITELIST_LIVE, weight table, style classes). The port reuses them verbatim.
- **`path-finder.scorePath` and the quota/ranking logic are pure TS** — only Cypher execution is
  DB-bound. The traversal *policies* don't need rewriting, only the traversal *engine*.
- **Embeddings are NOT in the public runtime.** They exist as node properties solely to feed
  `build_umap.py` → `publish_constellation.py` → static JSON. The 2.6GB baseline is
  embeddings-dominated; the *product content* (114,494 nodes / 147,862 rels, properties, no vectors)
  is tens of MB. (Discharges debate P0-2.)
- The UI is coherent and good: obsidian/terminal design system, radial hero, timeline ribbon,
  evidence drawer, command palette, path dialog, saved views, signature subgraphs. The sprint
  EXTENDS this system; no redesign.

## 2. Gate decisions (the five from the debate, discharged)

### G1 — Source of truth: the COMPOSED live graph content, sans embeddings
The public product is the FULL graph (incl. all Records — evidence pages are the product's soul).
**The bake input is a composition, not one pipeline** (review F2/F3): live Aura is built from the
projection (`build_graph_v2`/`load_neo4j_v2`) PLUS the operator-gated overlays — the identity attach
handoff (`data/review/attach/{nodes,edges}.jsonl`, which carries the 12 assertion-stamped SAME_AS)
and the COI loads (Membership/EconomicInterest). `scripts/bake_public_substrate.py` must compose the
same inputs `run_load` does. **S0 includes a source-of-truth proof**: the baked artifact must show
nonzero counts for `SAME_AS`-with-`assertion_id`, `Membership`, `EconomicInterest`, `INTEREST_IN`,
`DISCLOSED_AS`, `MEMBER`/`MEMBER_OF_ORG`, and `DERIVED_FROM_RECORD` — matched against live Aura
counts — before P1/P3/P4 are admitted to S3. Embeddings and `*_pending` staging props stripped.

### G2 — Substrate: one SQLite artifact + static JSON, replacing runQuery
`public-substrate.sqlite` shipped with the deploy (est. 40–120MB — C-task S0 measures; Vercel Node
functions allow 250MB uncompressed; if measurement busts the budget, fallback is Turso/libSQL with
the SAME schema — the decision is deferred behind one measured number, not re-designed):
- `nodes(id PK, type, search_label, props JSON)` + **generated/materialized columns for EVERY
  `propKeyForFactLabel()` key per type, with explicit rules for composite/fallback facts** (Filing
  period, EconomicInterest amount_band??amount, Agreement parties — review F4); browse reads
  materialized rows, never ad-hoc JSON extraction
- `edges(source, rel, target)` with covering indexes both directions
- `search_fts` (FTS5 over search_label/name/aliases + per-type key facts) + `search_rank`
- Precomputed tables: `entity_must_show`, `entity_phase2`, `neighbor_totals` — computed at bake by
  executing the same union/quota policies **without the live app's timeout fallbacks** (the baked
  values are the TRUE policy outputs; live timeout artifacts are documented as approved deltas —
  review F5). Known policy wart pinned or delta-approved explicitly: entity Phase-2 ranks Proceeding
  on `c.date` while live data uses `occurred_at` (entity-queries.ts:503 vs explorer-queries.ts:85).
- **Data queries are parameterized prepared SQL over the artifact** (review F6) — static JSON caches
  only for genuinely filterless views; query #4 carries a baked `as_of_date` surfaced in the
  response and UI label; #9's `window_days` is a SQL parameter with a date index
- Static JSON: status manifest, catalog, no-filter caches, constellation payloads — **including
  replacing `/api/constellation-manifest`, which is TODAY a live Neo4j route minting request-time
  signed URLs (review F1 — spec previously mis-stated it as already static); it becomes a baked
  manifest + static assets in S1**

**The graph engine**: a small TS module (`lib/server/graph-engine.ts`) loading adjacency from SQLite
(or an in-memory arc buffer built once per lambda instance — 148K edges ≈ single-digit MB) and
implementing: bounded k-hop expansion with per-type quotas (port of `buildExpandQuery` policy —
**including its request-state surface**: excluded node/edge types, already-loaded suppression,
include-universals, and the union edge-fetch semantics; and **reproducing the current outer-ordering
quirks** — e.g. the global `rank_value DESC` sort applied even to id-ranked types — unless a parity
delta is explicitly approved, review F7), bounded simple-path enumeration ≤4 hops (feeding the
EXISTING `scorePath`), and 1-hop tier-2 neighborhoods. All policies imported from the existing
vocabulary/quota modules. **S0 perf gates** (review F7): measured Vercel cold-start wall time and
heap after loading SQLite + engine indexes, with high-degree pathfind stress cases; the Turso/libSQL
fallback decision additionally requires remote-roundtrip benchmarks for expand/path if adjacency
cannot be held locally.

### G3 — Search: FTS5 with an explicit, versioned ranking contract
Lucene score parity is impossible and not worth chasing. The 3-bucket contract (exact-id → entities
→ records) and `search_rank` stay; BM25 replaces Lucene inside buckets. This is a DECLARED product
change with a golden-query test set (30 representative queries; ordering reviewed once by Stuart at
the parity gate, then frozen). Semantic search: **v2** (quantized vectors or Turso vector — not in
this sprint; nothing public uses vectors today).

### G4 — Feature scope: expand + path SHIP (no cuts)
They are the product's differentiation and the graph engine serves both. Sequenced last, behind the
parity harness. The only behavior deltas accepted: (a) search ranking (G3), (b) `date()`-current
queries get an "as of <build date>" label (data query #4, status), (c) path/expand timeouts vanish
(everything is local — strictly better).

### G5 — Cancellation gate (unchanged from review)
Aura paid stays until: parity harness green on all 7 surfaces over a replay corpus; zero
`neo4j-driver` imports reachable from public routes (lint rule + import test); one full
bake→deploy→smoke cycle from a clean checkout. Then cancel. Local Docker Neo4j remains the
pipeline's tool forever.

## 3. Parity harness (built FIRST — debate finding G/4)
`tests/parity/`: replay corpus of ~150 recorded request/response pairs per surface captured from
the LIVE app as **normalized semantic payloads** (review F9): strip/pin `built_at` and all
request-time fields; ignore signed-URL entropy; capture entity pages under conditions that avoid
timeout fallbacks (or mark fallback captures as non-authoritative); pin `as_of_date`; stabilize the
random home signature-subgraph pick. Runs against both backends during migration; the SQLite side
must match (or carry an explicitly-approved delta note, e.g. G3 ranking). The corpus is committed;
the capture script is rerunnable.

## 4. Product features (the identity dividend + underleverage closes)

| # | Feature | Where | Substrate need |
|---|---|---|---|
| P1 | **Verified-identity badges**: org pages show attached keys (EIN/SOS/committee chips) with "verified" state + an assertion-citation popover (assertion id, basis, decided_at, evidence links) | entity page hero + facts panel | **GATED on the S0 source-of-truth proof** (review F2): the stamped SAME_AS live in the attach overlay, not the projection — G1's composed bake must carry them or P1 defers |
| P2 | **Money rollups**: verified money-in/out totals + department breakdown on org pages; "follow the money" links into pre-filtered explorer | entity pages + data queries | precomputed rollup table at bake |
| P3 | **COI surfaces**: person pages gain a "disclosed interests" panel (Membership/EconomicInterest/INTEREST_IN); dual-role flags where a person holds a seat AND an interest in a county vendor | entity pages | **GATED on the S0 source-of-truth proof** (review F3): builders + vocabulary exist but inspected baked outputs carry none of these nodes/edges — prove the composed bake includes them or P3 defers |
| P4 | **Provenance-first evidence**: the evidence drawer gets record-lineage breadcrumbs (DERIVED_FROM_RECORD chain) + capture dates on every claim surface | evidence drawer | edges exist (72 in graph-v1), but the current loader reads only direct EVIDENCED_BY — P4 is a NEW materialized lineage table + query, not UI-only (review F8) |
| P5 | **Explorer polish**: overflow tray gets real per-node remaining counts (bake `neighbor_totals`); saved-view share URLs; "as of" data-currency chip in the toolbar | explorer | neighbor_totals table |
| P6 | **Data currency page**: /about gains per-source freshness (from the ingestion currency job manifest) | about + status | build manifest |

Explicitly v2 (named, not silent): semantic search; NL question→answer with citations; public
confidence-band exposure (needs its own policy doc per the identity-confidence spec §1.3).

## 5. Delivery plan

| # | Tranche | Contents | Size |
|---|---|---|---|
| S0 | Measure + capture + PROVE | composed bake-script skeleton (projection + attach overlay + COI overlay, sans embeddings → SQLite); SIZE vs 250MB budget; **source-of-truth proof** (8 identity/COI/lineage type counts vs live — gates P1/P3/P4); **perf gates** (Vercel cold-start + heap + high-degree path stress); normalized parity-corpus capture | S–M |
| S1 | Parity harness + static surfaces | harness runner; status/catalog manifests; **constellation-manifest → baked manifest + static assets** (review F1); `/api/data` 10 queries → parameterized prepared SQL (+ `as_of_date`); browse exact-parity on materialized columns | M |
| S2 | Search | FTS5 + bucket contract + golden-query set + Stuart ranking review | M |
| S3 | Entity pages | bake-time must-show/phase2/edges/neighbor-totals; entity routes read baked; P1+P2+P3+P4 land here (they're entity-page features) | M–L |
| S4 | Graph engine | expand + path on the TS engine; explorer wired; P5 | M–L |
| S5 | Cutover | G5 gate: full parity run; **reachability-aware import-boundary test** (public routes must not reach `@/lib/neo4j`/`neo4j-driver`; operator workbench routes explicitly exempt — a blanket grep would false-fail, review F10); clean-checkout bake→deploy; **cancel Aura**; P6 + Aura/Cypher copy cleanup on /data and /about (review F11) + docs | S |

Parallel track (from the durability discussion, unchanged): D1 ledger backup (destination still
pending Stuart); ingestion currency job (weekly Tammy-run poll→stage→refresh→digest) whose bake
step becomes the tail of this pipeline; GitHub Actions rebuild-and-deploy as D3.

Rules: same machine as R- and C-series — Codex executes under TDD, review-gated, parity fixtures
never weakened, ~1,500-line tranches, redaction scan on any artifact-shape change (baked substrate
inherits the graph's egress guarantees: it bakes only what the live public graph already exposes).

## 6. S0 source-of-truth proof — results (2026-07-07)

Local composed bake: 6,307 nodes / 21,236 edges / **14MB SQLite / 52ms + 76MB adjacency load** —
size & perf gates pass at projection scale. Live Aura: **130,480 nodes / 168,615 rels**. Verdicts:

1. **G1 REVISED (confirmed at scale): the projected JSONL dirs are a ~5% curated slice, not the
   graph.** The bake source becomes a **full live-graph export sans embeddings** (Aura today, local
   Docker post-cutover), composed with the attach overlay. Projection dirs feed only
   constellation/signature artifacts. **S0b: full export → re-bake → RE-MEASURE size/perf** — at
   ~20× nodes the 250MB budget is genuinely in play; the Turso fallback decision waits on that
   number, as designed.
2. **P3 CUT from v1**: the COI labels/edges (Membership, EconomicInterest, INTEREST_IN,
   DISCLOSED_AS, MEMBER, MEMBER_OF_ORG) are absent from LIVE Aura too — builders shipped, loads
   never ran. Reinstating P3 requires an operator-gated COI load first (own decision, own runbook).
3. **Identity-overlay drift found**: ledger/overlay carry 80 stamped SAME_AS; live has 59 stamped +
   22 legacy unstamped (pre-identity, empty props). Reconcile before the first real bake (drift
   report scope); overlay is authoritative for stamped rows. Legacy 22 stay as plain edges for
   parity (they can never be cited — join_citation is fail-closed) and get flagged for later audit.
4. P1 (identity badges) and P4 (lineage, 72 edges live) remain IN — their data is proven live.

## 7. Review round 1 (2026-07-07)

Codex adversarial review: 11 findings, all folded. The two that changed the plan: **F1** —
`/api/constellation-manifest` is a live Neo4j route (missed in the initial read; now S1 scope), and
**F2/F3** — the projection pipeline alone is NOT the live graph: the identity attach overlay (the 12
assertion-stamped SAME_AS) and COI loads are separate compositions, so G1 became a composed bake
with an S0 source-of-truth proof gating P1/P3/P4. Also folded: browse column materialization rules
(F4), timeout-artifact handling + the Proceeding ranking wart (F5), parameterized SQL + as_of_date
(F6), request-state + ordering-quirk parity and perf gates for the graph engine (F7), P4 rescoped as
a lineage table (F8), corpus normalization beyond timestamps (F9), reachability-aware import lint
(F10), copy cleanup (F11). Gate verdicts pre-fold: G1 FAIL→revised, G2 FAIL→revised, G3 PASS with
declared delta, G4 conditional PASS, G5 FAIL→revised. Review artifact: scratchpad
`substrate-spec-review.md` (session-local).
