# Identity-confidence architecture — design

**Date:** 2026-07-06 · **Author:** Claude (Fable 5) · **Status:** COMPLETE (2026-07-07) — C1a b1d6a0b · C1b 8305003 · C2 d241cc6 · C3 21a1a8f · C4 (this commit). Live confidence.jsonl: 241 records (92 medium/149 low/12 masked); highs unlock on a collision-context re-run. · **Input contract:** verdict-feed v1 (`scripts/verdict_feed.py`, R5).

## 0. The problem

The research waves produced a large class of cases the identity model deliberately cannot act on:
**likely-same organizations with no qualifying key sighting.** The SOS lane alone holds 113 advisory
`same` verdicts (conf 0.50–0.88); across all waves the bench shows 234 evidence-backed `same` rows.
The rubric is working as designed — nothing outside the CA-SOS registry ecosystem prints the SOS
number, so these can never satisfy the §9a auto lane, and most never will. Today they exist only as
`ai_reviews` sorting hints. The knowledge ("the county paid this LLC, and it is almost certainly
this registered entity") is real, evidenced, and **unused**.

The dangerous shortcut would be weakening SAME_AS. This design does the opposite: it gives graded
identity belief a first-class home **so that SAME_AS never has to soften.**

## 1. Decision summary (the argued position)

1. **A DERIVED confidence projection, not a second ledger.** New file
   `data/identity/confidence.jsonl` (gitignored, operator-local) holding `IdentityConfidence`
   records — a **rebuildable projection** of the verdict feeds + the assertion ledger, never an
   audit source of truth (the feeds are; review round 1 F2/F3/F8). Rebuild is idempotent and
   replaces in place. The IdentityAssertion ledger's status set stays untouched — its statuses are
   *decision* states; confidence is *belief*; `PUBLISHING_STATUSES` stays exactly
   `{deterministic, approved}`.
2. **Bands, not floats, at every consumption surface.** Records store the raw signal payload, but
   everything downstream sees `high | medium | low`. No surface ever renders "0.87" as if it were a
   calibrated probability — it is a signal, and the codebase already fought this battle once
   (`signal_strength` rename).
3. **Operator-local first; public exposure is a separate, explicitly-gated future decision.** No
   confidence-derived join reaches the public build in this milestone. The egress gate is not
   modified. A future "publish likely-links" decision requires its own policy doc + Stuart sign-off,
   exactly like §9a did. The payoff we CAN ship now — attribution rollups ("$X verified + $Y
   high-confidence") — lands in the operator bench and operator-side reports.
4. **Confidence records are promotable and supersedable, never authoritative.** An operator approve
   in the bench (existing flow) supersedes the confidence record with a real `approved` assertion; a
   future key sighting routes to the §9a lane; a `different`/contradiction verdict retires the
   record. Confidence never blocks or substitutes for either path.

## 2. The record (IdentityConfidence v1)

```jsonc
{
  "schema_version": "identity-confidence-v1",
  "id": "conf-<sha16 of subject|target>",                    // PAIR-stable (provenance is data, not identity — F8)
  "subject_ref": "org-casos-0526212",                        // registry anchor (matches ledger orientation)
  "target_ref": "org-marincontract-recipient-…",             // vendor
  "band": "high",                                            // high | medium | low (derived, §3)
  "signals": {                                               // raw inputs, never rendered directly
    "verdict": "same", "confidence": 0.86,
    "corroborating_dimensions": ["service_domain", "county_payment_context", "locale"],
    "name_signal": "normalized_name_exact"                   // from the candidate join, when present
  },
  "provenance": { "model": "…", "run": "…", "tranche": "…" },// verbatim from verdict-feed v1
  "evidence": [                                               // STRUCTURED, audit-safe shape (F7) — never bare strings
    {"source": "org_site|county_open_data|propublica|sos_registry|news|other",
     "supports": "same|context", "url_or_record_id": "…"}
  ],
  "source_row": {"gid": 1487, "run": "…"},                    // locator back to the raw research row
  "reason": "…",                                              // researcher free text — OPERATOR-ONLY render policy (F7)
  "status": "active",                                         // active | superseded_by_assertion | retired_contradicted | stale
  "superseded_by": null,                                      // assertion id when operator/§9a decides
  "computed_at": "…", "source_snapshot_hash": "…"            // fingerprint drift ⇒ stale (reuse identity_ledger.fingerprint)
}
```

One live record per (subject_ref, target_ref) — the pair-stable id IS the uniqueness constraint;
rebuild replaces in place (the projection is derived; the feeds are the audit trail).

**Derivation contract (review F1):** verdict-feed v1 does NOT carry corroboration dimensions, and
its validator rejects unknown fields. C1 therefore ships a minor schema rev, **verdict-feed v1.1**:
OPTIONAL validated fields `dimensions: string[]` (mapped from the raw research rows'
`registry_match_dims`) and `evidence: [{source, supports, url_or_record_id}]` (mapped from raw
`evidence[]`); `upgrade_legacy()` performs both mappings. v1 rows without them remain valid — they
simply cannot band above medium. Builder: new `scripts/identity_confidence.py` consuming
verdict-feed rows + read-model cases + the live assertion ledger; validate-fail-loud; every write
redaction-scanned (`scan_for_forbidden`) PLUS a structured-evidence shape check — raw `evidence[].fact`
free text is never copied wholesale into the projection.

## 3. Banding rule (v1 — deliberately dumb, revisable)

- **high**: verdict `same` ∧ confidence ≥ 0.80 ∧ ≥ 2 corroborating dimensions ∧ single candidate
  for the vendor ∧ no live collision (context check) ∧ not `needs_careful_review`.
- **medium**: verdict `same` ∧ confidence ≥ 0.65, otherwise failing exactly one high-criterion
  (except collision — a collision is never bandable above low).
- **low**: everything else that is still a live `same` verdict.
- `unsure`/`different` verdicts produce NO record (different additionally *retires* any live record
  for the pair).

The rule lives in ONE function with table-driven tests; the registry JSON (R4) gains a
`confidence_bands` block — and C1 explicitly WIDENS the fail-loud registry loader
(`reconciliation_registry.py` expected-top-level-keys), the TS codegen, and the byte-current
drift tests in the same tranche (review F4: the loader rejects unknown keys today, so a bare JSON
edit is a breaking change).

## 4. Consumption (this milestone)

1. **Bench**: a `band` chip on needs-review rows; filter + sort by band. **The raw-float
   affordances go away for confidence-backed rows** (review F9): the `ai` float sort becomes band
   ordering and the `signal_strength.toFixed(2)` detail rendering is removed (float visible only
   behind an explicit debug toggle). The 113-case SOS lane becomes a workable high→low queue.
2. **Attribution rollup (operator-side)**: extend the existing Neo4j consequence projection
   (`operator-context.ts` money query) with a per-vendor rollup artifact:
   `verified_total` (SAME_AS-joined) vs `high_confidence_total` vs `unattributed`. Surfaced on the
   bench detail pane. NOT in the public app.
3. ~~Dedup hints~~ — **DEFERRED out of v1** (review F6): confidence pairs are anchor↔vendor attach
   pairs with no natural home in the real-org↔real-org dedup candidate model, and any write near
   `dedup-assertions.jsonl` is one typo from the component assembler. Revisit only with a read-only
   annotation design.

## 5. Lifecycle & invariants

- **Promotion — read-side masking, not write-side transactions (review F2).** The decide/apply
  writers are NOT modified to touch the projection (no cross-file transaction). Instead: (a) every
  consumer (bench, rollups) masks any confidence record whose pair has a live publishing assertion
  — computed at read time from both files, so double-counting is impossible even mid-rebuild; and
  (b) the C2 reconciliation pass stamps `superseded_by_assertion` lazily on rebuild. Test:
  approve-during-rebuild yields correct rollups both before and after the stamp.
- **Contradiction — per-run input model (review F3).** `load_feed()`'s conflict-raise governs
  WITHIN one feed. Across runs, the builder compares the incoming run's rows against the EXISTING
  projection by pair index: a later `different`/refutation retires the live record
  (`retired_contradicted`, dissent-ratchet); history stays in the feeds, not the projection.
- **Drift**: `source_snapshot_hash` mismatch on rebuild ⇒ `stale` (re-derive from fresh verdicts);
  mirrors ledger fingerprint drift.
- **Hard invariants** (tested): `join_citation()` gains a FAIL-CLOSED schema guard — it must
  refuse any record whose id does not carry the `assertion-` prefix, regardless of status (review
  F5 proved empirically that today a `conf-*` row with `status: "approved"` would be cited; the
  invariant must be a boundary, not a convention). Plus: no SAME_AS edge ever cites a `conf-*` id;
  the public build contains no confidence artifact (build-exclusion test like the operator route
  group); `PUBLISHING_STATUSES` byte-unchanged; egress consumers proven to load only
  `data/identity/assertions.jsonl`.

## 6. Non-goals (v1)

Calibrated probabilities; public exposure of likely-links; auto-promotion at any band; committee/EIN
lanes (records are lane-generic but the SOS advisory pool is the only populated input today);
ML-learned banding.

## 7. Delivery plan

| # | Step | Size |
|---|------|------|
| C1 | verdict-feed v1.1 (optional dimensions/evidence, legacy mapping) + `identity_confidence.py` (pair-stable records, banding fn, builder, structured-evidence + redaction gates) + registry `confidence_bands` (loader widening + codegen + drift tests) | M |
| C2 | Lifecycle: read-side assertion masking in all consumers + lazy supersession stamping on rebuild; per-run contradiction retirement; drift staleness; approve-during-rebuild race test | S–M |
| C3 | Bench band chip + filter + rollup pane (operator-context rollup query) | M |
| C4 | Invariant suite (fail-closed `join_citation` guard, egress isolation, public-build exclusion, byte parity) + backfill over the live verdict feeds → first real `confidence.jsonl` | S |

Same execution rhythm as the refactor: Codex under TDD, review-gated, byte-parity fixtures held,
~1,500-line ceiling per tranche.

## 8. Review round 1 (2026-07-06)

Codex adversarial review: 9 findings, all folded. The structural one: F2/F3/F8 jointly showed the
draft was quietly treating confidence as a second ledger — reframed as a **derived, rebuildable
projection** (pair-stable ids, read-side masking instead of write transactions, per-run
contradiction handling; the feeds remain the audit truth). F1 → verdict-feed v1.1 derivation
contract; F4 → registry loader widening in-tranche; F5 (empirically demonstrated) → fail-closed
`join_citation` schema guard; F6 → dedup hints deferred out of v1; F7 → structured evidence shape +
operator-only reason rendering; F9 → bench float affordances retired for confidence-backed rows.
Review artifact: scratchpad `confidence-spec-review.md` (session-local).
