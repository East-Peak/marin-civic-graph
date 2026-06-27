# Civic Reconciliation Toolkit — Tranche 1 Design Spec

**Date:** 2026-06-27
**Status:** Design approved (Codex-converged, 3 rounds → green). Spec under review.
**Scope:** Backend foundation for a generic, region-agnostic civic-data reconciliation toolkit. Split into two autonomous build goals (Goal 0, Goal 1). The reconciliation **workbench UI is Tranche 2** and out of scope here.

---

## 1. Context & Intent

Open Marin is a public civic-accountability graph (Neo4j + Next.js) that makes public money and political influence legible — its flagship output being "dual-role" organizations that both receive public money and act politically (lobby/donate).

The decision driving this spec: generalize the Marin-specific identity-reconciliation machinery into a **generic, open-source, region-agnostic toolkit** other municipalities can adopt — a "reconciliation workbench" modeled on RevOps dedup tools (Salesforce / HubSpot / DataGroomr): side-by-side record compare, confidence + AI recommendation, merge / reject / unsure — with one civic superpower beyond standard CRM dedup: **preview what a join *does* to the graph**. Generic-by-design from the start; Marin is the first wired adapter.

### What already exists (shipped, ~1,400 tests, Codex-hardened, byte-stable)

- **`org_resolution`** — the matcher/resolver. Region-clean (0 region literals).
- **Identity Control A ledger** (`identity_ledger`) — versioned, supersedable `IdentityAssertion`s with status / basis / reviewer / snapshot-hash / fingerprints / supersession / requeue.
- **Egress / redaction gate** (`identity_egress_gate`) — `publishable_*` filters, scan-for-forbidden.
- **Dedup engine** (`dedup_org_candidates`, `dedup_merge_applier`) — tombstone canonical-merge, edge repoint (node tombstone = property, label kept; edges collapse via `apoc.merge.relationship`).
- **Source "lanes"** — de-facto adapters: EIN (IRS BMF), sos_id (CA-SOS), committee_id (FPPC). Region/source-specific, correctly.
- **AI adjudicator** — triages candidate joins → same / different / unsure + signal strength + cited reason (plural, advisory).

Measurement (2026-06-26): the core engine is already region-clean; region code is correctly concentrated in adapters. So this is **interface extraction, not a rewrite.**

### The invariant: three-layer safety model

Every concept and data flow below preserves the existing three-layer separation. Nothing collapses these:

1. **Candidate generation** — propose links; never mutate the graph.
2. **Ledger assertion** — operator decisions recorded as versioned, supersedable assertions.
3. **Egress / application** — redacted publication; dedup application to the graph.

A wrong merge is a false public claim about a real named entity (high, asymmetric cost). The safety model is non-negotiable.

---

## 2. Non-Goals (scope fence)

Out of scope for Tranche 1 (later tranches):

- The **workbench UI** (Tranche 2).
- **Blast-radius compute** — the read model carries refs/hooks only; computing "what this join does" is Tranche 2.
- **Self-serve city onboarding** (configuring new sources via UI/config).
- **New sources / new adapters** beyond wrapping Marin's existing lanes.
- **`relationship_candidate` and `pattern_candidate` case types** — reserved enum values only; never emitted, never actioned, and rejected by the Tranche-1 validator.

---

## 3. Architecture Overview

A thin generic core is extracted **around** the existing hardened engine. The engine internals (resolver, ledger, dedup applier) are not rewritten.

```
            ┌──────────────────────── generic core (NEW) ────────────────────────┐
 capture    │  Reconciliation        IdentityKey         Candidate read-model     │
 adapters   │  adapters (interface)   registry            emitter (versioned)      │
 (existing) │      │                     │                     │                   │
 ingest_*   │   emit_refs()         normalizer/prefix/     ReconciliationCase      │
 normalize_*│   emit_candidates()   semantics/eligibility   + CandidateJoin (ev.)  │
            │   coverage_report()   → generated compat      + EntityRef            │
            │   redaction_policy()     views (parity-       redaction boundary     │
            │      │                    tested)                  │                  │
            └──────┼─────────────────────┼─────────────────────┼──────────────────┘
                   ▼                      ▼                     ▼
        existing hardened engine:  org_resolution · identity_ledger · dedup · egress gate
                                          │
                                   IdentityAssertion ledger  ◄── OperatorAction (UI input shape)
```

**Two adapter roles** (Codex's distinction): *capture* adapters (existing `ingest_*`/`normalize_*`, untouched internals — CA-SOS streams a 3.6 GB file, BMF withholds conflicts, FPPC has election-year gating) vs the new *reconciliation* adapter interface that the core consumes uniformly.

---

## 4. Goal 0 (pre-tranche) — IdentityKey Registry Extraction

A self-contained, provable-invariant goal. **Scope: registry + generated views + parity/contradiction tests ONLY.** No emitter, no cases.

### 4.1 Registry entry schema

A registry entry is keyed by the composite **(`key_type`, `semantics_scope`)** — a single key type can hold **multiple scoped entries** (this is what lets `committee_id` be both self-identity and relationship-only; see §4.5). Each entry:

| field | meaning |
|---|---|
| `key_type` | e.g. `ein`, `sos_id`, `committee_id` |
| `semantics_scope` | the context this entry governs, e.g. `self`, `self_committee`, `related_committee_pointer` (the composite key with `key_type`) |
| `normalizer` | callable: raw → canonical key string |
| `anchor_prefix` | the org-id prefix for the key's anchor node (e.g. `org-bmf-ein-`) |
| `eligible_entity_classes` | which entity classes this entry may apply to |
| `key_semantics` | one of `self` / `parent` / `fiscal_sponsor` / `dba` / `committee` / `project` |
| `allowed_merge_semantics` | which semantics permit a SAME_AS merge (typically `self` only) |
| `relationship_only` | true → this entry denotes a relationship, never an identity merge |
| `dedup_eligibility` | whether this entry participates in dedup component formation |

`anchor_prefix` is shared across scoped entries of the same `key_type` (it identifies the anchor node, which is scope-independent). The duplicate-`anchor_prefix` contradiction check (§4.4) therefore fires on a collision **across distinct `key_type`s**, not across scoped entries of the same key type.

### 4.2 Generated compatibility views

The registry **generates** today's scattered constants — `KEY_NORMALIZERS`, `ANCHOR_PREFIXES`, `_DEDUP_KEYS`, `_KEY_BEARING_BASES` — preserving existing import sites and order. Consumers keep importing the same names; the values now come from the registry.

### 4.3 Parity tests (the safety gate)

Before *any* consumer change: assert the generated views equal today's literal values and behavior, key-by-key. The existing ~1,400-test suite stays green throughout. (Pattern: the Phase B set-parity test — the generated view is the guarantor.)

### 4.4 Fail-loud contradiction tests

The registry validator must **reject** at load time:

- `relationship_only = true` together with `dedup_eligibility = true`
- non-`self` `key_semantics` with merge eligibility
- duplicate `anchor_prefix` (across distinct `key_type`s; see §4.1)
- unknown `normalizer`
- `eligible_entity_classes` / key mismatch
- scoped entries of the same `key_type` declaring **different `normalizer`s** — all scoped entries of a `key_type` must share one normalizer (because `KEY_NORMALIZERS` is generated by `key_type`, §4.2)

### 4.5 `committee_id` semantics (two scoped entries)

`committee_id` is expressed as **two scoped entries** (per the composite key, §4.1):

- **`(committee_id, self_committee)`** — `key_semantics: self`, `eligible_entity_classes: [committee]`, merge-eligible, dedup-eligible. The committee's own identity. (`key_semantics: self` is what the existing guardrail treats as mergeable; the `[committee]` class scopes it to committee entities.)
- **`(committee_id, related_committee_pointer)`** — `relationship_only: true`, dedup-ineligible, **not** merge-eligible. Used when a `committee_id` appears as a related committee/PAC pointer on a **non-committee** endpoint.

The validator enforces that `related_committee_pointer` is `relationship_only=true` + `dedup_eligibility=false` (§4.4).

---

## 5. Goal 1 (Tranche 1) — Reconciliation Cases + Read-Model Emitter

Depends on Goal 0. **Backend only.**

### 5.1 Core concepts

- **`ReconciliationCase`** — the top-level unit. `case_type` **active** ∈ {`identity_key_attach`, `entity_dedup_merge`}; **reserved** ∈ {`relationship_candidate`, `pattern_candidate`} (enum-known, validator-rejected, never emitted/actioned). Each active type carries its own allowed actions + safety rules.
- **`CandidateJoin`** — a pairwise **evidence** object *inside* a case (not the universal unit): `left_ref`, `right_ref`, `signals`, `signal_strength`.
- **`EntityRef`** — a normalized source endpoint: `source_id`, `local_id`, `display_name`, typed public fields, provenance. (The graph `Record` type is unchanged and remains strictly evidence/provenance — `EntityRef` is a distinct name to avoid a parallel model.)

### 5.2 Decisions = the existing ledger (no new model)

There is **no new durable Decision model**. The existing `IdentityAssertion` ledger is the decision log (status/basis/reviewer/snapshot-hash/fingerprints/supersession/requeue intact). Tranche 1 models an **`OperatorAction`** — the write-command *shape* the UI will emit (Tranche 2) — which writes ledger assertions.

**Ledger namespacing (safety-critical) — pinned contract:** attach-assertions and dedup-assertions are kept separate so an attach row can **never** enter a dedup merge component:

- **Attach / key ledger:** `data/identity/assertions.jsonl` (and existing per-phase files, e.g. `data/identity/county-resolution-assertions.jsonl`). These carry attach/key bases (anything *not* prefixed `org_dedup`).
- **Dedup ledger:** `data/identity/dedup-assertions.jsonl`. Dedup assertions are identified by `basis` prefixed **`org_dedup`** (e.g. `org_dedup_key_exact`).
- **Merge-component assembly reads ONLY `org_dedup`-basis assertions.** Attach/key bases are read only by key-surfacing / export, never by merge-component assembly.
- **Precedence when both are loaded is `basis`-filtering, not status alone** — i.e. a row's eligibility for a merge component is decided by its `org_dedup` basis prefix, independent of its status.

### 5.2.1 Action matrix (per active case type)

Each active case type permits exactly these `OperatorAction`s, each writing to a specific ledger namespace + basis. No other actions are valid (the validator rejects them); reserved case types permit **no** actions.

| `case_type` | action | effect | writes to | `basis` |
|---|---|---|---|---|
| `identity_key_attach` | `approve` | attach key (assertion + SAME_AS) | attach ledger (`assertions.jsonl`) | attach/key basis (e.g. `operator_approved_<key>`); **never** `org_dedup*` |
| `identity_key_attach` | `reject` | record non-match | attach ledger | attach rejection basis |
| `identity_key_attach` | `unsure` | no write; stays queued | — | — |
| `entity_dedup_merge` | `approve` | apply MergePlan (§5.3) | dedup ledger (`dedup-assertions.jsonl`) | `org_dedup*` |
| `entity_dedup_merge` | `reject` | record non-merge | dedup ledger | dedup rejection basis |
| `entity_dedup_merge` | `unsure` | no write; stays queued | — | — |

### 5.3 MergePlan (entity_dedup_merge only)

Split from any identity decision. Fields: `canonical_id`, `superseded_ids`, `edge_ops_count`, `selfloop_drops`, `collision_count`. Two policies stated **separately**:

- **Node policy:** `tombstone_no_field_merge` (tombstone via property, label kept; no field survivorship).
- **Edge policy:** parallel edges collapse via `apoc.merge.relationship` (this is *not* "no merge").

`identity_key_attach` cases have **no** MergePlan (no survivorship concept).

### 5.4 Redaction boundary (single emit gate)

The emitter is the one redaction gate. Per-adapter field-level policy: `public_fields` / `forbidden_fields` / `pii_class`. The emitter serializes **only** `public_fields`, then runs a recursive forbidden-key / sentinel scan over the **final** JSONL. This generalizes today's CA-SOS-specific redaction.

**Hashes inside the boundary:** `subject_fingerprint`, `target_fingerprint`, `input_hash`, `source_snapshot_hash` are emitted **only if** computed purely from public material; otherwise they stay ledger-local and are **not** emitted. The same boundary covers `ai_reviews`, coverage reports, and graph-context refs.

### 5.5 Candidate read model (the versioned JSONL contract)

One source-agnostic, versioned contract — collapsing today's scattered candidate outputs + adjudicator verdicts. **Each JSONL row is a `ReconciliationCase` envelope, not a flat candidate row.** A row contains `candidate_joins[]`: an `identity_key_attach` case has exactly **one** join; an `entity_dedup_merge` case has **one-or-more** joins (the component's pairwise edges) plus component-level fields.

**Case-envelope (row) fields:**

| field | notes |
|---|---|
| `schema_version` | contract version |
| `case_id`, `case_type` | stable identifiers (`case_type` ∈ active set; reserved types never appear) |
| `candidate_joins[]` | the pairwise joins (see below) |
| `actionability` | **case/component-scoped** (one decision per case, not per join) |
| `current_ledger_status` | from the ledger (approved/rejected/superseded/requeued/none) |
| `ledger_assertion_refs[]` | links to assertions |
| `ai_reviews[]` | plural, advisory; each: model+prompt version, public `input_hash`, `verdict`, `reason`, `signal_strength`, `created_at`, `cited_fields`. **Never sets the ledger.** |
| `component` | dedup only: `{component_id/case_group_id, sibling_candidates, competing_candidates_per_endpoint, refused_reasons, hard_key_conflicts}` |
| `merge_plan?` | **`entity_dedup_merge` only:** the dedup dry-run plan (§5.3) — `canonical_id`, `superseded_ids`, `edge_ops_count`, `selfloop_drops`, `collision_count`. Computed offline from the projected graph (the existing dedup dry-run does this); the richer *visual* blast-radius is Tranche 2. Absent for `identity_key_attach`. |
| `graph_context_refs` | neighborhood + blast-radius **hooks (refs only)**; visual compute is Tranche 2 |

**Per-join (`candidate_joins[]` element) fields:**

| field | notes |
|---|---|
| `candidate_id` | stable per-join id |
| `left_ref`, `right_ref` | `EntityRef`s, **public_fields only** |
| `signals` | match signals |
| `signal_strength` | per-join strength |
| `subject_fingerprint?`, `target_fingerprint?` | only if public-derived (§5.4) |
| `requeue_reason?` | if fingerprints drifted |

Naming: `signal_strength` for reconciliation artifacts; `confidence` reserved for established graph facts.

### 5.6 Reconciliation-adapter interface

Wraps existing lanes (internals untouched). Methods: `emit_refs()`, `emit_candidates(existing_refs)`, `coverage_report()`, `redaction_policy()`.

### 5.7 Five golden UI packets (the contract's acceptance tests)

The emitter contract must pass all five (UI-shaped, so backend-first cannot design the wrong contract). Each has a pinned invariant:

1. **exact key attach** — `case_type=identity_key_attach`, exactly one `candidate_join`, no `component`, `actionability` permits `approve`.
2. **many candidates for one org** — multiple sibling cases/joins for one endpoint surface in `component.competing_candidates_per_endpoint`; no two are independently approvable as `self` for the same key.
3. **prior rejection / superseded** — `current_ledger_status` reflects the ledger; a rejected/superseded case is **not** re-presented as freshly actionable.
4. **dedup component merge** — `case_type=entity_dedup_merge`, one-or-more joins, a `component` with `component_id`, one **case-scoped** `actionability` (not per-join); only `org_dedup*`-basis assertions assemble it.
5. **relationship-demotion** — appears **only** as `component.refused_reasons` / a competing signal inside an active case; it never produces a `relationship_candidate` case row.

---

## 6. Testing Strategy

- **Strict TDD** (red/green) throughout.
- **Goal 0:** parity tests (generated == today's) asserted before consumer changes; fail-loud contradiction tests; existing suite green.
- **Goal 1:** schema-validated round-trip/contract tests on the read model; the emitter validated against the five golden packets; existing suite green as the extraction safety net.
- No live-DB / no network inside any autonomous build loop.

---

## 7. Open-Source / Safety Boundary

- Tranche-1 package fixtures are **synthetic or redacted golden rows only**.
- No raw `data/review` or `data/identity` files become package fixtures.
- The redaction model, ledger semantics, and registry are publishable by design (civic-tech transparency; no credentials, no PII).

---

## 8. Build Sequencing

1. **Goal 0** — IdentityKey registry extraction. Its own Codex-hardened `/goal` doc.
2. **Goal 1** — reconciliation cases + read-model emitter. Its own Codex-hardened `/goal` doc.

Each goal: strict TDD, no live-DB/network in the loop, git push to origin the only egress. The workbench UI (Tranche 2) follows, consuming the read model from Goal 1.

---

## 9. Provenance

Design converged via three adversarial Codex rounds (2026-06-27): v1 (flat `CandidateJoin`/`Decision`/`Survivorship`) → RED; v2 (`ReconciliationCase`, reuse-the-ledger, per-adapter redaction) → RED-but-close; v3 (two-goal split, reserved case types, explicit ledger namespacing, redaction-covers-hashes) → **GREEN, ready to spec.**
