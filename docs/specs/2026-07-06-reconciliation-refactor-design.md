# Reconciliation subsystem — whole-vertical architecture assessment & refactor design

**Date:** 2026-07-06 · **Author:** Claude (Fable 5), full-vertical read (~5.5k lines Python across 18
modules, ~1k lines bench TS) · **Status:** DRAFT — pending Codex adversarial review + Stuart go/no-go.

## 0. Verdict

**Refactor in place; do not rewrite.** The identity core (`identity_ledger`, `identity_key_registry`,
`identity_egress_gate`, `reconcile_writer`) is craft-quality: deterministic assertion ids,
fingerprint/supersession semantics, fail-loud registry validation, acyclic import DAG, atomic
locked writes, redaction gates enforced in code. The debt is at the **seams**: the lane pattern was
copy-adapted five times instead of abstracted, key-semantics knowledge is duplicated in ~6 places,
naming encodes tranche history instead of architecture, and the verdict feed is a convention rather
than a schema. None of it is load-bearing rot; all of it taxes every future lane, county, and the
upcoming identity-confidence work.

## 1. What exists (map)

```
Layer 1 — candidate generation
  org_resolution.py           shared resolver (key-exact merge | name signals; never merges on name)
  enrich_org_keys.py          Lane 1: IRS BMF → EIN refs + resolve        (422)
  enrich_casos_keys.py        Lane 2: CA-SOS stream → sos_id + redaction  (641)
  enrich_fppc_keys.py         Lane 3: FPPC committee_id, year-gated       (321)
  enrich_county_vendor_eins   Phase B: vendors → EIN candidates           (283)
  enrich_county_vendor_sos    Phase C: vendors → sos_id candidates        (360)
  dedup_org_candidates.py     resolver pointed inward (org↔org)           (431)

Layer 2 — decision ledger
  identity_ledger.py          IdentityAssertion: statuses, supersession, requeue matrix (219)
  identity_key_registry.py    key semantics declarations + generated views (222)
  identity_key_normalizers.py stdlib-only canonicalizers                   (68)
  identity_resolution_adapter signal_strength rename + merge guardrail     (68)
  identity_legacy_projection  flat approved-files → ledger, no audit bypass (91)

Layer 3 — egress + apply
  identity_egress_gate.py     the ONLY path decision → published join      (125)
  dedup_merge_applier.py      reversible merge, full preimage journal      (244)

Read/write model (operator surface)
  Naming rule: reconciliation_* = domain/read side; reconcile_* = operator write actions.
  reconciliation_cases.py     domain model (ReconciliationCase envelope)   (134)
  reconciliation_adapters.py  candidate artifacts → CandidateJoin          (148)
  reconciliation_read_model   emitter: adapters+ledger+verdicts → JSONL    (451)
  reconciliation_overlay.py   live-ledger overlay for the bench queue      (73)
  reconcile_decide.py         case + decision → writer call                (158)
  reconcile_writer.py         locked/atomic/idempotent ledger writes       (192)
  reconcile_auto_policy.py    §9a preview/drift-check/apply                (476)

Bench (operator-local TS)
  bench-logic.ts / bench-types.ts / Bench.tsx / operator-context.ts / operator-python.ts (~1k)
```

Invariants that hold everywhere (verified by reading, protected by 155 test files): keys are never
fabricated; name similarity never merges; relationship semantics never become SAME_AS; attach and
dedup assertions live in separate namespaces; egress fails closed; person data never lands in a
durable artifact.

## 2. Findings (ranked)

### F1 — The lane pattern is copy-adapted ×5, and the registry is under-consumed  [HIGH]
Every lane re-implements: runtime normalizer registration, blocking/prefilter, candidate enrichment
(`registry_*` fields), `build_*_attach` (assertion + SAME_AS pair — `build_ein_attach`,
`build_sos_attach`, `build_committee_attach` share one structure; the committee variant additionally
**lacks the `policy_hash`/`eligibility_snapshot_hash` parameters** the other two carry — promoted to
defect F8d), coverage report, `_write_jsonl`, `_load_existing_orgs`, CLI `main`. Docstrings say it
out loud: "mirrors Lane 1", "mirrors build_ein_attach", "third lane on the shipped machinery".

Worse, the **key → anchor-prefix → public-field** knowledge is scattered (Codex-verified 2026-07-06,
with per-site nuance):
1. `identity_key_registry.REGISTRY` (identity_key_registry.py:50-75) — the intended single source,
   but it declares only key/prefix semantics; it does NOT yet declare the read-model public-field
   names (`registry_ein` etc.) — which is precisely the gap R3 closes.
2. `reconcile_decide._LANES` + `_ein_anchor`/`_sos_anchor` (reconcile_decide.py:24-40) — re-declares
   routing, field names, and source stamps; omits `committee_id` (F8b).
3. `reconciliation_read_model._ADAPTERS_BY_SOURCE`/`_KEY_FIELD_BY_SOURCE`/`detect_source()`
   (reconciliation_read_model.py:307-333) — prefixes AND field names, third copy.
4. `bench-logic.ts KEY_FIELD` (bench-logic.ts:19-24) — fourth copy, hand-mirrored in TS.
5. `reconcile_auto_policy.literal_proposed_key()` (reconcile_auto_policy.py:50-55) — hardcodes two
   of three prefixes (F8a).
6. Lane-level prefix knowledge: named constants in the EIN/FPPC lanes
   (enrich_county_vendor_eins.py:38, enrich_fppc_keys.py:38-41) but **literal string construction**
   in the SOS lane (enrich_casos_keys.py:127-130) — the worst form of the duplication.

Registry Goal 0 states the intent — "a new region declares its keys here once" — but adding a lane
today touches ~8 files. This is the central refactor target.

### F2 — Runtime normalizer registration is a vestigial landmine  [HIGH]
`KEY_NORMALIZERS` is a mutable shared dict; `sos_id`/`committee_id` register at lane-module import.
Consumers must call `register_*_normalizer()` defensively — `dedup_org_candidates` calls both in
three separate functions; `enrich_county_vendor_sos` depends on Lane 2's import side effect. The
pattern exists solely to keep `org_resolution.py` byte-identical during the migration era
(BASE_SHA parity locks). That constraint is historical: the registry already knows
`runtime_registered` per entry and can generate the complete dict statically.

### F3 — Naming encodes tranche history, not architecture  [MEDIUM]
`reconcile_cases.py` (queue overlay) vs `reconciliation_cases.py` (domain model) is a genuine trap.
The `reconcile_*` vs `reconciliation_*` prefix split is *almost* a rule (actions vs domain) but is
nowhere stated and `reconcile_cases` violates it (it's a read-path module).

### F4 — `confidence` → `signal_strength` rename leaks across the codebase  [MEDIUM]
The rename-at-artifact-edge decision is right, but there is no single chokepoint:
`normalize_resolution_candidate_for_artifact()` is called per-lane, `reconciliation_adapters`
falls back with `raw.get("signal_strength", raw.get("confidence"))`, `ai_reviews_from_verdicts`
reads both, tranche artifacts carry both. Every new consumer must know both names forever.

### F5 — The (vendor, anchor) pair convention is re-derived in four in-repo places  [MEDIUM]
`left_ref` = vendor, `right_ref` = registry anchor; `subject` = anchor, `target` = vendor. This
inversion is re-implemented (each with a warning comment!) in `reconcile_cases._pair` (:18-22),
`reconcile_decide.decide` (:82-99), `reconcile_auto_policy._vendor_id/_anchor_id/_case_literal_key`
(:78-96), and `bench-logic vendorId/proposedKey` (:28-37). (The research-fleet scripts outside the
repo parsed `case_id` by string-split — a fifth, external consumer of the same tribal convention.)
One accessor module (mirrored TS) should own it.

### F6 — The verdict feed is a convention, not a schema  [MEDIUM — blocks identity-confidence]
The read model has `SCHEMA_VERSION`; verdicts have nothing. Pilot verdicts, scale-shard verdicts
(prefixed keys + `source_proposed_key` normalization in auto_policy), shard-3 tranche rows, and
overlay artifacts all differ in shape. The upcoming identity-confidence architecture will make
advisory verdicts a first-class, durable input — it needs a versioned schema + validator now,
not a fourth ad-hoc shape.

### F7 — Status/bucket semantics are hand-mirrored between Python and TS  [LOW-MEDIUM]
`_ACTIONABILITY` (py) vs `bucketOf/REJECTED/DONE/KNOWN_STATUSES` (ts). The repo already solved this
class of problem once: `registry/node-types.json` → codegen'd `node-types.generated.ts` +
`canonical_type.py`. Reconciliation statuses deserve the same treatment.

### F8 — Latent defects found during the read  [FIX NOW]
a. `reconcile_auto_policy.literal_proposed_key()` strips `org-bmf-ein-`/`org-casos-` but not
   `org-fppc-` — a committee auto-candidate would silently keep its prefixed key and fail every
   pair join (invisible ineligibility, no error).
b. `reconcile_decide._LANES` supports only `ein`/`sos_id`; the bench's `KEY_FIELD` and the read
   model's `CommitteeAdapter` both advertise `committee_id`. An operator approving a committee case
   gets `unsupported source for decide` at write time — wire Lane 3 through decide, or make the
   bench hide/flag committee rows.
c. `reconcile_auto_policy.apply_batch(policy_version=RESEARCH_POLICY_REVIEWER)` — the reviewer
   string doubles as the policy version. Assertions record `policy_version:
   "research-fleet-v1/policy-stuart-2026-07-01"`, conflating two distinct audit fields.
d. `build_committee_attach` (enrich_fppc_keys.py:263-297) lacks the `policy_hash` /
   `eligibility_snapshot_hash` parameters that `build_ein_attach`/`build_sos_attach` carry — Lane 3
   structurally cannot record §9a audit hashes. Harmless today (committee isn't wired into decide,
   F8b) but the two gaps compound: wiring F8b without fixing F8d would silently drop audit fields.
e. `reconcile_auto_policy` writes durable artifacts (`normalize-verdicts` output, preview JSON —
   which carries researcher free-text `reason` and evidence fields) through raw `_write_json`/
   `_write_jsonl` (:38-47, :389-407) with **no `scan_for_forbidden` redaction gate**, unlike the
   read-model emitter (:279-293). The verdict pipeline's person-data floor currently rests on
   upstream discipline alone.
f. The read-model CLI passes `allow_missing=True` for every `--ledger` argument
   (reconciliation_read_model.py:435-438), so a typoed ledger path silently yields
   `current_ledger_status: none` across the board — despite `load_ledger()` being purpose-built to
   fail loud on missing paths (:156-167). An explicitly supplied ledger path must exist.

### F9 — Non-findings (deliberate, keep)  [FOR THE RECORD]
The bench's subprocess bridge (TS → `execFileSync` python) is right for an operator-local tool.
The JSONL-file ledger is right at this scale (atomic, lockfile, .bak). The reserved case types and
the dedup/attach namespace split are sound. Do not "modernize" these.

## 3. Refactor plan (parity-locked, TDD, Codex-executable)

The codebase already invented the right migration discipline — BASE_SHA parity locks (generate the
old constant from the new source, byte-compare in tests, then rewire consumers). Every step below
reuses it. Each step is a separate tranche: red tests → green → Codex review → next.

| # | Step | Contents | Acceptance | Size |
|---|------|----------|------------|------|
| R0 | Fix F8 defects | fppc prefix in `literal_proposed_key` (drive from registry `ANCHOR_PREFIXES`); split `policy_version` from reviewer; add `policy_hash`/`eligibility_snapshot_hash` params to `build_committee_attach` (F8d); **redaction-gate all `reconcile_auto_policy` artifact writes** (F8e: wrap `_write_json`/`_write_jsonl` with `scan_for_forbidden` + tests); **fail loud on missing explicit `--ledger`** (F8f); committee rows: bench marks them explicitly non-actionable + decide returns a purposeful error naming R3 (full Lane 3 wiring is R3 scope — wiring it here without the candidate-file path through `operator-python.ts DATA` + the decide route would still fail from the bench, per review Finding 3) | new regression tests incl. an e2e committee-rejection path; 155 files stay green | S |
| R1 | Naming + accessor unification (F3, F5) | rename `reconcile_cases.py` → `reconciliation_overlay.py` with an **executable CLI shim** (the bench shells the literal script filename via `operator-python.ts:37-38` + two routes — an import-only shim breaks `/api/reconcile/cases`, per review Finding 1); migrate the route/DATA references in the same tranche + a route-level subprocess test; new `reconciliation_refs.py` with `vendor_ref_of/anchor_ref_of/literal_key_of`; mirrored `caseRefs()` in TS; delete the four re-derivations; module-map docstring stating the naming rule | byte-fixture parity (see rules below); old script path proven working until routes migrated | S–M |
| R2 | Static normalizer registry (F2) | registry generates the COMPLETE `KEY_NORMALIZERS` (all four keys) as an **immutable read-through view** (`MappingProxyType`) preserving today's clobber-refusal semantics (review Finding 8 — a plain dict + no-op shims lets a foreign mutation persist silently); `register_*_normalizer()` become validating no-op shims; drop defensive calls; add an `org_resolution.py` **source-hash sentinel test** (review Finding 10 — the never-edit discipline is currently untested) | parity test: generated view == post-registration dict today; clobber-refusal tests stay green | S |
| R4 | Status/registry codegen to TS (F7) — **moved before R3** | `registry/reconciliation.json` (statuses, buckets, key fields, anchor prefixes) → codegen'd TS + imported by Python; same pattern as node-types. Sequenced before R3 because R3's TS-side derivations consume this codegen (review Finding 2) | drift test both sides | S |
| R3 | Lane framework (F1, F4, F6) | extend `IdentityKeyEntry` with `public_key_field`, `anchor_source`, `attach_basis`, and **`anchor_subject_fields`** (per-lane subject projection — the committee subject carries `entity_class: "committee"` + `source: "fppc"`, which the egress guardrail depends on; a thin generic builder would drop them, per review Finding 9); ONE `build_attach(entry, …)` with **subject-payload parity tests for all three lanes** before replacement; ONE `emit_candidate()` chokepoint (signal_strength rename + `registry_*` enrichment); `detect_source`/`_LANES`/`_KEY_FIELD_BY_SOURCE`/TS `KEY_FIELD` derive from the registry (TS from R4 codegen); **remove or public-hash-validate the serialized `subject_fingerprint`/`target_fingerprint` join fields** (review Finding 6 — they contradict the emitter's own redaction docstring); full Lane 3 decide/bench/candidate-path wiring + e2e committee approve test | byte-fixture parity across all lanes; "new lane" checklist = registry entry + adapter public-fields + tests | M–L |
| R5 | Verdict schema v1 (F6→feed) | `verdict_feed.py`: versioned row schema (vendor_id, literal proposed_key, verdict, confidence, provenance{model, run, tranche}, optional verification block), validator, loader with **explicit duplicate policy — identical duplicates collapse; CONFLICTING duplicates fail loud and surface in coverage, never silent last-write-wins** (review Finding 11: eligibility is an audit chain; silent compaction can erase contradictions); apply-time **fresh collision-context requirement** — apply consumes a context artifact generated within the same run, hash-recorded (review Finding 12: today a stale `--context` file lets a post-preview SAME_AS collision through); `reconciliation_read_model --verdicts` + `reconcile_auto_policy` consume it; migrate checkpoint feeds once | round-trip tests over pilot + scale + tranche feeds incl. duplicate/conflict cases; auto_policy preview hash unchanged on migrated clean inputs | M |

Sequencing: **R0 → R1 → R2 → R4 → R3 → R5** (R4 hoisted before R3 — review Finding 2). R0–R2 are
cheap and de-risk R3. R5 lands last and is the direct enabler of the identity-confidence
architecture (its design doc should consume the R5 schema as its input contract).

Rules of engagement (house style + review Finding 4): strict red/green TDD; **each tranche opens by
hash-pinning byte fixtures** (a real-ish mixed EIN/SOS/committee read-model packet + an auto-policy
preview) — the existing golden-packet tests assert shape/leak-cleanliness, NOT bytes, so they alone
cannot certify "byte-identical" acceptance; parity locks before any consumer rewire; Codex
adversarial review per tranche; ~1,500-line diff decomposition ceiling; never touch
`data/identity/*` from tests (scratch mirrors); redaction scan on any artifact-shape change.

## 5. Review round 1 (2026-07-06)

Two-part Codex adversarial review (fact-check + plan-risk), 7 + 12 findings, **all folded**:
fact-check confirmed F8a/b/c and F2 verbatim, trimmed F1/F5 overstatements (registry lacks
public-field names — now R3's explicit job; SOS lane uses literal prefix construction; four in-repo
pair re-derivations, not five), and surfaced F8d. Plan-risk review added F8e/F8f, re-sequenced
R4 before R3, hardened R1 (executable shim), R2 (immutable view + source-hash sentinel), R3
(subject-payload parity, fingerprint-field cleanup), R5 (duplicate-conflict policy, fresh collision
context), and replaced "golden packets" acceptance with hash-pinned byte fixtures throughout.
Review artifacts: scratchpad `refactor-spec-review-{facts,risks}.md` (session-local).

## 4. What this buys

- **New lane/new county cost** drops from ~8 files to a registry entry + adapter fields — the
  toolkit's own Goal 0, actually realized.
- **Identity-confidence architecture** gets a typed, versioned verdict input instead of a fourth
  ad-hoc shape, and a single candidate-emission chokepoint to attach confidence sidecars to.
- **Bench/Python drift** becomes structurally impossible (codegen) instead of convention.
- Three latent defects fixed before they bite (F8a would have silently excluded any future
  committee auto-candidate — precisely the failure mode this system is designed to refuse).
