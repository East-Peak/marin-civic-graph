# Identity Attach Workbench — Tranche 2 (v1) Design Spec

**Date:** 2026-06-27
**Status:** Design approved (Codex design + spec reviewed). Spec under review.
**Scope:** The operator-local **identity attach workbench** — a DataGroomr/RevOps-style merge bench over the Tranche-1 read model, letting the operator clear the 216 needs-review + bulk-confirm the 729 recommended identity-key attaches, writing decisions to the Identity Control A ledger. The public dual-role view, dedup-merge cases, and the rich interactive graph blast-radius are **later tranches**.

---

## 1. Context & Intent

Tranche 1 shipped the backend toolkit (Goal 0 registry + Goal 1 cases/emitter). The Goal-1 read model is a versioned JSONL of `ReconciliationCase` envelopes; validated on real data (2,265 attach cases — 1,301 EIN + 964 sos — leak-clean) at `data/review/reconciliation/read-model.jsonl`. Decisions map through `reconciliation_read_model.operator_action_to_ledger` → `build_*_attach` / `make_assertion` → the ledger (`data/identity/*.jsonl`, gitignored, operator-local).

**First slice = the reconcile workbench** — the immediate need, and it *produces* the keyed data the eventual public dual-role view requires. The motivation is the genealogy-style "see it" insight: review candidates visually, not by comparing CSVs.

**Architectural driver:** the existing Next.js app is **Neo4j-backed, read-only, no auth, deployed-public**. The reconcile bench is **operator-local**: reads the read-model JSONL + the gitignored ledger, queries Neo4j for context, and **writes** decisions locally. It must be *physically impossible* to write from the deployed build.

**Cardinal rule:** the human owns every public identity claim; the AI verdict is advisory triage only; no person/address data ever reaches the browser (UI shows only read-model public fields + a whitelisted Neo4j projection).

---

## 2. Non-Goals (later tranches)
- The public dual-role view (deployed, read-only).
- Dedup-merge cases (need graph component/merge-plan context not in the attach read model).
- The rich interactive graph blast-radius (v1 ships a lightweight consequence summary).
- The `individual_agent` badge as UI (its boolean *is* added to the read-model contract in §5.4 for bulk-gating, but rendering it is v2).
- Auth / multi-operator.
- **Any write capability, route, page, or API under `/reconcile` on the deployed public build.**

---

## 3. Architecture Overview

```
 OPERATOR (local: `npm run dev:operator`  →  next dev -H 127.0.0.1, OPERATOR_WORKBENCH=1)
   │
   ▼  /reconcile (page) + /api/reconcile/*  ── ALL operator-only; build-excluded from public ──┐
   │  GET  /api/reconcile/cases    → read-model JSONL + live ledger overlay (ledger_status)      │
   │  GET  /api/reconcile/context  → batched, whitelisted Neo4j projection                       │
   │  POST /api/reconcile/decide   → server-side WRITER                                          │
   ▼                                                                                             ▼
 reconcile_writer  ── file-lock → load ledger → validate → operator_action_to_ledger →           │
                      upsert/supersede by assertion id → atomic write (temp+fsync+bak+rename)     │
                                                                                                 │
                 ledger: data/identity/*.jsonl (assertions)  +  SAME_AS handoff: data/review/attach/edges.jsonl
```

The **public build** mounts NONE of `/reconcile` or `/api/reconcile/*` — only generic shared components (cytoscape, etc.) that other public pages already use. Guaranteed by physical exclusion + a build test (§5.1).

---

## 4. Read Path

### 4.1 `GET /api/reconcile/cases` — static read model + live ledger overlay
Reads the read-model JSONL and **overlays current ledger status dynamically** (never mutates the file): per case, recompute via Goal 1's `ledger_status(load_ledger(...), subject_ref, target_ref, now=...)` over the live local ledger, where — matching `build_attach_read_model` — **`subject_ref = join.right_ref.local_id` (the registry anchor)** and **`target_ref = join.left_ref.local_id` (the vendor org)**. The queue (needs-review / recommended / rejected / done) reflects decisions made this session.

### 4.2 `GET /api/reconcile/context` — batched, whitelisted
Given a batch of vendor org ids, returns ONLY: public `display_label` (the real vendor name — enrichment gap #1), money-in total, money-flow count, paying departments, and a **key-collision hint**. Collision is computed from **all three**: the current ledger, the SAME_AS handoff artifact, and the live graph (a decision not yet applied to the graph still counts). Fixed whitelisted `runQuery` — no raw nodes, no PII.

---

## 5. Write Path (operator-only, fail-closed)

### 5.1 Physical non-deployability (Codex CRITICAL + HIGH)
- Operator code lives **outside** `src/app`: `app/operator-workbench-src/**` (the `/reconcile` page + `/api/reconcile/*` routes).
- `app/scripts/copy-operator-workbench.mjs` **always `rm -rf`s** the gitignored destination `app/src/app/(operator-workbench)/**` first, then copies in **only when `OPERATOR_WORKBENCH=1`**. Wired into `predev` + `prebuild` (alongside the existing `copy-subgraphs.mjs`). Fail-closed: a public build always deletes any stale copy.
- **`dev:operator` script** = `OPERATOR_WORKBENCH=1 next dev -H 127.0.0.1` (loopback), with a matching **`predev:operator`** = `OPERATOR_WORKBENCH=1 node scripts/copy-operator-workbench.mjs && node scripts/copy-subgraphs.mjs` (Codex r2: npm runs `predev:<name>` for `dev:operator`, NOT `predev` — so the copy must be wired to `predev:operator`, else operator routes aren't copied). Public `predev`/`prebuild` keep the fail-closed `rm -rf` (no copy without `OPERATOR_WORKBENCH`). Route-level gates (defense-in-depth): require `OPERATOR_WORKBENCH=1`, refuse if `VERCEL` set, strict `Host`/`Origin` allowlist, a random startup token, and a **server-fixed ledger path** (never request-configurable).
- **Build test:** delete `.next`; run public `npm run build` with `OPERATOR_WORKBENCH` unset; fail if `.next/server/app-paths-manifest.json` is absent OR contains any `/api/reconcile/*` or `/reconcile` path. **Stale-copy regression:** run an operator copy/build first, then a public build, and assert the operator routes are gone.

### 5.2 The writer (Codex CRITICAL — persistence + SAME_AS)
A single server-side writer, under a **file lock** (mutex around the whole read-modify-write so concurrent POSTs can't lose updates):
1. Load the current ledger (`load_ledger`, fail-loud on missing path unless explicitly empty).
2. Validate case + action (`validate_case` / `validate_action`).
3. Build the assertion via `operator_action_to_ledger` (+ `same_as` for approve).
4. **Upsert by assertion id**; if the operator changes a prior live decision, `identity_ledger.supersede` it (no duplicate row).
5. **Atomic write:** `write_assertions` to a temp file → fsync temp + parent dir → write `.bak` → `rename`.
6. Return `created | existing | superseded`.

**SAME_AS materialization — NODE + EDGE (Codex CRITICAL, r2):** `export_existing_orgs --enriched` surfaces a key ONLY from a live-graph `SAME_AS` edge (carrying an `assertion_id` that validates against the ledger) — it does **not** derive edges from ledger-only assertions. And the real load (`data/review/run_load.py` → `scripts/load_neo4j_v2.py`) creates an edge ONLY when both endpoints already exist; a fresh key-anchor (`org-bmf-ein-*` / `org-casos-*` / `org-fppc-*`) is NOT guaranteed in the graph. So an approve must atomically (with the ledger write) materialize ALL of: (a) the ledger assertion; (b) the **key-anchor node** upsert → `data/review/attach/nodes.jsonl`; (c) the `same_as` edge → `data/review/attach/edges.jsonl` (mirroring `build_*_attach`'s returned edge). The existing operator-gated `run_load` applies node+edge to the graph (separate step; the workbench never writes Neo4j). **Acceptance test (three cases):** ledger-only → key NOT surfaced; edge-only with a missing anchor node → NOT surfaced; node + edge + ledger → surfaced through the real export validation path.

**Idempotent retry vs fail-loud (Codex r2):** `assertion_id` = `(subject_ref, target_ref, basis, snapshot_hash)` — it excludes `decided_at`/`reviewer`. So a re-submit of the SAME decision must be idempotent: on a matching id, the writer KEEPS the existing assertion (returns `existing`, ignoring a regenerated `decided_at`) rather than fail-loud. A genuinely different decision changes `basis` (rejection-kind, §5.4) or `snapshot_hash` → a different id → `supersede`. Fail-loud is reserved for a true same-id-with-different-*decision* (which the basis/snapshot encoding now prevents). Tests cover the retry path.

### 5.3 Bulk path (rule-gated; Codex HIGH)
Uses `candidate_joins[].signal_strength` / `ai_reviews[].signal_strength` (NOT `confidence` — the read model maps it away) and the new `bulk_eligible` flag (§5.4). Eligibility requires ALL: `bulk_eligible == true`, exactly one candidate for the vendor's key, no competing candidate, no key collision (per §4.2), `current_ledger_status == none`, exact/normalized-name signal, AI `same` ≥ threshold, no careful-review flag. **Absent flags ⇒ ineligible** (fail-safe). Operator gets a typed confirmation with counts; each eligible case writes its OWN assertion (per-case audit), never a blanket record.

### 5.4 Required Goal-1 contract refinements (additive; re-verified)
Two small, additive changes to the Tranche-1 modules this tranche depends on (versioned read-model bump; tests updated + re-run):
- **`operator_action_to_ledger` reject basis encodes the kind** — `operator_rejected_<key>_<rejection_kind>` (attach) and `org_dedup_operator_rejected_<rejection_kind>` (dedup). Without this, switching `current_evidence` ↔ `entity_distinct` collides on the same assertion id (id = subject/target/basis/snapshot, excludes status), so supersession can't mint a clean id. Same-id/different-payload must fail loud.
- **Read-model contract bump** — emit per-case `review_flags` (incl. `needs_careful_review`, routed through the sos adapter) + a computed `bulk_eligible` boolean. Bump `schema_version`. The bulk path (§5.3) consumes these; absent ⇒ ineligible.

---

## 6. Bench UX
Left **queue** (needs-review by $ desc / recommended / rejected / done — by overlaid status). Center **case**: side-by-side vendor (County; real display name + money-in) vs registry (IRS/CA-SOS public fields), the **AI review** (verdict + signal_strength + reason), and the **lightweight consequence summary** ($ total · #flows · departments + the key-collision/dedup hint). Actions: **Approve / Reject (kind) / Unsure** + keyboard nav. Decisions POST to `/api/reconcile/decide`; the row status updates from the writer's response.

---

## 7. Testing
- **Build test (the safety guarantee):** §5.1 — fresh public build's `app-paths-manifest.json` has no operator routes; stale-copy regression; operator build mounts them.
- **Writer:** atomicity (no partial file on simulated failure; temp+rename), idempotency (re-submit → `existing`), supersession (changed decision supersedes; changed rejection-kind mints a clean id — exercises §5.4), file-lock under concurrent submits, attach basis never `org_dedup*`, fail-loud on missing ledger path.
- **SAME_AS handoff (3 cases):** ledger-only → key NOT surfaced by `export_existing_orgs --enriched`; edge-only with a missing anchor node → NOT surfaced; node + edge + ledger → surfaced. Plus the idempotent-retry test (re-submit → `existing`, regenerated `decided_at` ignored).
- **Read overlay:** a ledger-approved case shows `approved`, not the static `none`; read-model file never mutated; ref direction correct.
- **Bulk gating:** ineligible cases (competitor / collision / weak signal / `needs_careful_review` / absent flags) excluded; typed-confirmation count correct.
- **Context redaction:** only whitelisted fields; leak scan over the response clean.
- **Contract refinements (§5.4):** rejection-kind basis + `review_flags`/`bulk_eligible` emit; the existing Goal-1 tests updated + green; the Python suite stays green via `.venv/bin/python -m pytest`.
- **Component tests** (vitest) for the queue, side-by-side, decision flow. `npm run verify` green ×2; the existing 473 frontend tests stay green.

---

## 8. Build Sequencing (units)
1. **Goal-1 contract refinements (§5.4)** first — the rejection-kind basis + `review_flags`/`bulk_eligible` bump + re-run the read model; Python suite green.
2. The **read endpoints** (`/api/reconcile/cases` overlay; `/api/reconcile/context` whitelisted) + tests.
3. The **writer** (lock/load/validate/upsert/supersede/atomic + SAME_AS handoff artifact) + tests — riskiest; pin first on the write side.
4. The **operator route group + copy-script + build-exclusion + build test + runtime gates** — the safety guarantee.
5. The **bench UI** (queue + side-by-side + AI + consequence + decide + keyboard) + component tests.
6. The **bulk rule-gated** path + typed confirmation.
7. Final: `npm run verify` ×2; Python suite green; the build test proves non-deployability; existing tests green.

---

## 9. Provenance
Codex design review + spec review (2026-06-27): direction affirmed (web workbench, attach-only v1, lightweight consequence); the write architecture was reworked across both rounds — build-excluded fail-closed route (copy-script + manifest build test + stale-copy regression), atomic/locked/superseding writer, SAME_AS materialized into a handoff artifact (export reads graph edges, not ledger-only assertions), `bulk_eligible`/`review_flags` contract bump with rejection-kind-encoded basis, whitelisted batched context, dynamic ledger overlay. Write-path safety mechanism (build-excluded route + build test) chosen by Stuart.
