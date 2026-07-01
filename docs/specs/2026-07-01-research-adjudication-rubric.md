# Research Adjudication Rubric — deep-research verdicts for the Attach Workbench

**Date:** 2026-07-01
**Status:** GREEN — Codex-converged in 3 rounds (15 → 4 → 2 LOW nits, all folded). Next: calibration pilot (§7).
**Scope:** V1 of the deep-research adjudication fleet: Claude-Code-owned research agents that investigate identity-attach candidates (County vendor == IRS/CA-SOS registry entity?) wall-to-wall online and emit evidence-backed verdicts into the EXISTING read-model pipe. Replaces the synthetic county-keying adjudicator's verdicts. The bench (Tranche-2 Slices 1–3.1) renders them; the human still owns every attach.

---

## 1. Context & intent

The workbench queue holds 2,265 attach cases (1,788 needs-review / 477 bulk-eligible). The current
`ai_reviews` come from a heuristic single-pass adjudicator (name/city reasoning only). Measured
distribution over needs-review: 1,320 "different" / 300 "same" / 167 "unsure". The operator's real
job is finding the true attaches; today that means hand-researching each candidate.

**This spec defines a research fleet that does the operator's research for them**: for each case,
an agent fetches the authoritative registry record for the proposed key, sweeps the vendor's public
footprint (registries, 990s, official sites, news), and emits a verdict with citations. An
adversarial verifier tries to refute it. Output feeds `reconciliation_read_model.py --verdicts`
unchanged; the bench then shows *"same 0.94 — EIN appears on the org's 2023 990; SOS address matches
the County record"* with links, and review collapses from research to confirmation.

**Cardinal rule preserved:** verdicts are advisory. Nothing here writes the ledger, the graph, or
the handoff. The operator (or the rule-gated, typed-count bulk path) makes every decision.

## 2. Non-goals (V1)

- No auto-writes of any decision. No change to `reconcile_writer` / `reconcile_decide`.
- No natural-person research (see §5 guard). No person data in any emitted artifact.
- No standalone/generalized research service (that is V2, after this pattern proves out here).
- No re-scoring of `signal_strength` on candidate joins; only `ai_reviews` are replaced.
- Not deterministic/golden: research verdicts are a timestamped, provenance-stamped advisory layer.
  They are regenerable, never byte-stable, and never gate any deterministic test.

## 3. Output contract

**Append log:** agents append rows to `data/review/research-adjudicated/verdicts-research.log.jsonl`.
**Feed file:** a tiny deterministic compactor produces `verdicts-research.jsonl` from the log —
exactly one row per `(vendor_id, proposed_key)`, **last append wins** (log order is the authority;
`researched_at` is provenance only, since agent-provided timestamps can skew, and the compactor
rejects rows with malformed timestamps). Only the compacted file ever feeds the read model, so
resume/re-run duplicates are structurally impossible downstream. Both files live under `data/review/` (gitignored,
operator-local).

Row shape:

```json
{
  "vendor_id": "org-marincontract-recipient-wra",
  "proposed_key": "1085358",
  "lane": "sos_id",
  "verdict": "same",                    // same | different | unsure  (pipe vocabulary)
  "confidence": 0.94,                   // read model maps → signal_strength
  "reason": "<= 60 words, org-level facts only (display line for the bench)",
  "research_summary": "fuller org-level narrative (ignored by the pipe; audit/UI later)",
  "conflicts": ["unexplained or resolved conflicts, org-level"],
  "evidence": [ {
      "fact": "org-level paraphrase; for filings include form + year + entity name + key observed",
      "url": "…",
      "source": "propublica|irs|bizfile|org_site|990|grants|news|gov|other",
      "accessed_at": "<ISO8601>",
      "supports": "identity|key_sighting|distinction|status"
  } ],
  "key_sighted": true,                  // §4 — the literal key on vendor-controlled/vendor-filed material
  "registry_match_dims": ["address", "activity"],  // which identity dimensions matched (§4)
  "vendor_name": "WRA INCORPORATED",    // picked up by cited_fields for display
  "registry_name": "Wra, Inc.",
  "adjudicator": "claude-research-fleet",
  "adjudicator_version": "v1",
  "model": "<model id>",
  "researched_at": "<ISO8601>",
  "cost": {"web_ops": 8, "tokens_est": 0},
  "verifier": {"ran": true, "refuted": false, "note": "<= 40 words"}
}
```

Pipe compatibility: `ai_reviews_from_verdicts` consumes `vendor_id`/`proposed_key`/`verdict`/
`confidence`/`reason` and ignores extras, so the compacted file feeds the CLI **unchanged** (with
`model`/`created_at` metadata set via its existing params). Rendering `evidence` links in the bench
is a small follow-on UI slice; until then the reason text carries the substance.

**Emission rules (redaction floor):** the schema has NO person fields, and no free-text field
(`reason`, `research_summary`, `conflicts`, `evidence[].fact`, `verifier.note`) may contain a
natural-person name, personal address, email, phone, or personal identifier — write "leadership
overlaps" never the officer's name. Org names, org principal addresses, and public registry fields
are fine. Evidence URLs must be org-level pages (an officer/person profile page is not citable; use
the org page that contains the fact). **Leak checks are structured, not one regex:** scans for
email/phone/street-address patterns and person-name shapes (title-case, ALL-CAPS, 2–3 token, with
initials/suffixes) diffed against an `allowed_org_name_set` — the registry + vendor names PLUS
org aliases/DBAs discovered during research (person-name-shaped orgs like law firms and memorial
foundations are legitimate; the set carries org names only, never personal identifiers); any
non-allowed hit ⇒ the row is rewritten or dropped to `unsure`. In the pilot, all output rows are
additionally human-read (30 rows).

## 4. The rubric — decision bars

The agent answers ONE bounded question: **is the County vendor the same real-world organization as
the registry entity that holds the proposed key?** The anchors (key, registry public fields, County
money context: paying departments + dollars) are inputs, not things to rediscover.

**Evidence dimensions**, in two tiers:

- **HARD (independently probative):**
  - `key_sighted` — the **literal key** appears on material **outside the key's own registry**,
    tying the vendor to the key. Per lane:
    - **EIN:** the IRS/BMF/TEOS record (and its ProPublica mirror) is the anchor and NEVER
      qualifies. Qualifying: the literal EIN on the org's own site, the org's own 990 (a
      vendor-authored filing, distinct from the BMF row), grant/award or government contract pages
      naming the vendor with the EIN.
    - **SOS:** NO document held by or filed to the CA SOS qualifies — the SOS record AND its
      Statements of Information are the registry itself (SOI facts feed the *address-match* and
      *filing-continuity* dimensions instead, never `key_sighted`). Qualifying: the literal entity
      number on the vendor's own site/materials, government award or county contract pages naming
      the vendor with the entity number.
    Rationale: `key_sighted` later unlocks the §9 bulk lane, so it must be evidence the registry
    could not have produced about itself.
  - **Official filing continuity** — registry filings (990 trajectory, SOS statements of
    information) that connect the registry entity to the vendor's documented address/operations.
  - **Evidenced name lineage** — rename / DBA / merger documented by a filing, news item, or the
    org's own materials (never assumed from similarity).
  - **Authoritative address match** — registry principal address == the vendor's own published
    address (from the vendor side, not the registry echoing itself).
- **SOFT (supporting only; mutually reinforcing and often from one source):** activity/line of
  business consistent with the paying departments; Marin-plausible geography; leadership overlap
  (may be *used*, never *emitted*); web co-mentions.

**SAME** requires ALL of:
- identity consistency across **≥2 dimensions beyond the name**, of which **at least one is HARD
  when `confidence >= 0.9`** (soft dimensions can support, never carry, a high-confidence SAME);
- **no unresolved distinguishing fact** (an unexplained conflict on any dimension forces `unsure`);
- an out-of-area principal address needs an evidenced explanation (e.g. HQ elsewhere with
  documented Marin operations).

**DIFFERENT** requires a **positive distinguishing fact** with evidence — never absence of
evidence. At `confidence >= 0.9` the fact must be **incompatible**, not merely non-supporting:
the entity was dissolved/inactive before the payment period, formation postdates the money flows,
the key's org is a provably distinct same-named entity (different jurisdiction + no connection),
or an official source proves unrelated identity. "Different line of business" or "no Marin nexus
found" alone caps DIFFERENT at 0.7–0.89.

**UNSURE** is the default and the honest fallback: name-only similarity (however exact), conflicting
sources (name the conflict in `conflicts`), thin footprint, tool failures, or the §5 person guard.

**Confidence semantics (calibrated, not vibes):**
- `>= 0.9` — bet-the-ledger: multiple independent confirmations incl. the hard-dimension
  requirement above, zero unexplained conflicts.
- `0.7–0.89` — strong with one identified gap (named in `reason`).
- `< 0.7` — SAME and DIFFERENT are forbidden below 0.7; the verdict becomes `unsure`.

## 5. Process contract (per case)

0. **Person-shape triage (BEFORE any web operation):** if the vendor label appears to be a natural
   person or sole proprietor (person-shaped name, no organizational suffix), emit `unsure` with
   reason "vendor label appears to be an individual; person research is out of scope" and STOP — no
   search containing the person-shaped name is ever issued. If genuinely ambiguous (e.g. "SMITH
   ASSOCIATES"), search only organization-framed terms (label + "Marin" + org context), and stop at
   the first person-indicating signal.
1. **Registry first:** fetch the canonical record for the key (EIN → ProPublica Nonprofit Explorer
   `/organizations/<9-digit EIN>`, IRS TEOS; SOS → bizfile entity search). This is the anchor's
   ground truth: legal name, address, status, formation, officers-for-reasoning.
2. **Vendor footprint:** search the vendor name + Marin context; fetch the org's own site and 1–2
   independent sources (990s, GuideStar, local news, government award pages).
3. **Diff and decide** per §4. Budget: ~6–10 web operations per case; when exhausted, verdict on
   what was gathered (thin ⇒ `unsure` — never stretch).
4. Agents never read `data/identity/`, the read model, or bench state; they receive ONLY their
   frozen case input (§7) and write ONLY their verdict row.
5. **Transient-use rule:** person-level observations (officers seen in a 990, SOI, or news item)
   may inform reasoning in the moment but may not be written to ANY durable artifact — verdict
   rows, manifests, logs, research caches, scratch files. Every retained run artifact passes the
   same §3 redaction floor as the verdict rows.

## 6. Adversarial verification

An independent skeptic agent tries to **refute** the researcher using the cited evidence:
(a) does each URL actually support its `fact`? (b) is there a distinguishing fact the researcher
missed? (c) for batched vendors (§8), review the vendor's FULL candidate set — when any candidate
is `same`, confirm the per-pair distinguishing facts actually discriminate between candidates.
Refuted ⇒ the row is downgraded to `unsure`, both sides summarized, and the pre-downgrade position
is preserved for audit/calibration (`verifier.refuted = true`, `verifier.original_verdict`,
`verifier.original_confidence` — refutation rates are reported by original class). Verification
uses the same emission rules.

**Coverage:** pilot = 100% of everything. At scale: 100% of `same` (any confidence), 100% of
`different >= 0.9`, 100% of `key_sighted = true` rows, 100% of top-decile-$ cases, and a 20% sample
of the remainder; sampled refutation rates per class are reported in the run manifest and an
elevated rate (>10% in any class) pauses the run for rubric review.

## 7. Calibration pilot (gates the fleet — nothing scales until this passes)

- **Set:** 30 cases, stratified: 10 heuristic-"same" (mix of name-exact and fuzzy), 10
  heuristic-"different" (include high-$ ones), 8 heuristic-"unsure", 2 `needs_careful_review`.
  Selected by Claude, listed by case_id.
- **Blind protocol (leak-proof by construction):** the 30 case inputs (candidate join fields +
  money context only) are **frozen to a file BEFORE Stuart labels anything**. Agents run from the
  frozen file only — no repo access, no read model, no ledger, no bench state. Stuart's labels and
  the fleet run can then proceed in either order.
- **Ground truth:** Stuart decides those 30 in the bench (his ledger decisions ARE the labels).
- **Grading — all six must hold:**
  1. **Zero false-SAME**: no fleet-`same` that Stuart rejected. One occurrence fails the pilot.
  2. **Agreement ≥ 93%** on positioned cases. *Positioned = fleet verdict ∈ {same, different};
     fleet-`unsure` rows are excluded from this denominator by definition* (gates 4–5 are the
     anti-abstention controls).
  3. **High-confidence perfection:** fleet `same` at ≥0.9 agrees with Stuart 100%.
  4. **Coverage (anti-unsure-gaming):** the fleet takes a position on ≥ 2/3 of cases overall AND
     within each stratum — it cannot pass by abstaining on the hard ones.
  5. **Recall of true attaches:** of the cases Stuart approves, the fleet said `same` on ≥ 75%
     (an over-cautious fleet that misses the actual attaches is useless even if precise).
  6. **Unsure honesty:** fleet-`unsure` cases skew toward ones Stuart found hard/slow (qualitative
     read of the diff, together).
- **Output:** a per-case diff report (fleet vs human, with evidence) reviewed together; rubric
  amendments folded and, if material, a 10-case re-run of the affected class.
- The 30-case pilot is a **smoke gate**, sized to catch systematic rubric failures, not to prove
  rare-error rates. The bulk-expansion lane has its own larger precision gate (§9).

## 8. Scale run (after the pilot passes)

- **Scope:** operator's call at pilot review — the ~467 questionable (heuristic same+unsure), or all
  1,788 needs-review, or all 2,265 (re-adjudicate everything; feeds §9 bulk expansion).
- **Orchestration:** a Claude-Code-owned workflow — `pipeline(cases, research, verify)` with
  bounded concurrency, per-case structured output, and a **hard token/cost ceiling set by Stuart
  before launch**. Resumable: rows append to the log; a re-run skips pairs already in the compacted
  feed. The run emits a **manifest**: attempted / completed / failed / dropped-by-leak-check /
  stopped-at-ceiling counts, per-class refutation rates, and per-case `cost` — a ceiling stop is
  loud, never silent truncation.
- **Batching:** candidates sharing a vendor (or an anchor) run in one agent with a shared research
  cache, but each pair gets its OWN verdict row with per-pair distinguishing facts (§6c guards the
  cross-contamination risk: one conclusion may not be smeared across the candidate set).
- **After the run:** compact the log, regenerate the read model with `--verdicts` pointed at the
  compacted file (existing runbook), restart the bench, review the re-bucketed queue.

## 9. Downstream follow-ons (separate slices, not V1)

- **Bulk-eligibility expansion:** today's bulk gate requires the mechanical `normalized_name_exact`
  signal — high precision, poor recall ("10,000 Degrees" vs "Ten Thousand Degrees" fails). After
  calibration, `_compute_bulk_eligible` gains a research lane requiring ALL of:
  `verdict == same` AND **`key_sighted == true`** (the literal-key-on-vendor-material bar — soft
  registry-field agreement NEVER qualifies) AND `confidence >= 0.9` AND `verifier.ran AND NOT
  refuted` AND single candidate AND not `needs_careful_review`. Name-exactness is no longer
  required — the mechanical anchor is replaced by a *harder* mechanical anchor (a literal key
  sighting), not by agent judgment.
  **Bulk-expansion gate (in addition to the pilot):** before the lane is enabled, Stuart reviews a
  stratified sample (n ≥ 40; EIN/SOS × exact/fuzzy × $ tiers) of research-bulk-qualifying rows in
  the bench with their evidence; **zero false-SAME required**. Additive read-model contract bump
  (schema_version), TDD + Codex like every read-model change. The typed-count human confirmation
  and the client collision gate stay exactly as they are.
- **Evidence links in the bench:** render `evidence[]` (and the verifier note) in the AI panel.
- **V2 generalized tool:** productize the fleet (own repo, batch API, any entity-resolution
  dataset) once the pattern has cleared real Marin volume.

## 10. Audit & provenance

The append log + compacted feed are the audit artifacts: every row carries model, version,
timestamps, evidence URLs with access times, per-case cost, and the verifier outcome. Both are
operator-local (gitignored) like all `data/review/` products. Ledger assertions continue to record
only the operator's decision; research provenance stays in the advisory layer. If a research
verdict later proves wrong, the fix is the normal one: supersede the assertion in the bench (the
writer already handles supersession), fix/re-run the affected rows, recompact, regenerate.

---

## Codex review rounds

### Round 1 — 2026-07-01 (gpt-5.5 xhigh, spec inlined): 15 findings (2 CRITICAL / 5 HIGH / 5 MEDIUM / 3 LOW) — ALL FOLDED

1. **CRITICAL** `key_corroborated` overclaimable (SOS field-match collapsed into it) → renamed
   `key_sighted`, literal-key-on-vendor-material only; registry-field agreement explicitly excluded (§4).
2. **CRITICAL** bulk expansion unsafe on soft corroboration → bulk lane now requires `key_sighted`
   + verifier-confirmed + ≥0.9; plus its own n≥40 zero-false-SAME gate (§9).
3. **HIGH** SAME's "2 dimensions" could both be soft → HARD/SOFT tiering; ≥0.9 SAME requires ≥1 HARD (§4).
4. **HIGH** overconfident DIFFERENT → ≥0.9 DIFFERENT requires an incompatible fact; nexus-absence caps at 0.89 (§4).
5. **HIGH** 30 cases can't prove rare-error rates → pilot reframed as smoke gate; larger precision
   gate attached to the bulk lane specifically (§7, §9).
6. **HIGH** agreement gameable by unsure-spam → coverage ≥2/3 overall+per-stratum AND recall ≥75%
   of human-approved attaches added as gates 4–5 (§7).
7. **HIGH** blind-run leakage → inputs frozen to a file before labeling; agents get only the frozen file (§7).
8. **MEDIUM** leak scan brittle → structured multi-pattern checks + no-person-fields schema +
   100% human read of pilot output (§3).
9. **MEDIUM** person guard ran after searching → moved to step 0, pre-search, with the ambiguous-label
   protocol (§5).
10. **MEDIUM** evidence not machine-checkable → `accessed_at`/`source`/`supports` enums + filing
    granularity requirements (§3).
11. **MEDIUM** 20% DIFFERENT sampling too weak → coverage matrix (100% same, 100% different≥0.9,
    100% key_sighted, 100% top-decile-$) + refutation-rate circuit breaker (§6).
12. **MEDIUM** vendor-batching cross-contamination → per-pair verdict rows + verifier reviews the
    vendor's full candidate set (§6c, §8).
13. **LOW** 60-word reason too tight → `research_summary`/`conflicts` extras (pipe ignores them) (§3).
14. **LOW** duplicate/supersede semantics undefined → append log + deterministic compactor,
    one row per pair, latest wins (§3, §10).
15. **LOW** cost ceiling not operationalized → per-case `cost` + run manifest with loud ceiling-stop (§8).

**Round-1 verdict: another-round-needed** → v2.

### Round 2 — 2026-07-01: 4 findings (1 HIGH / 1 MEDIUM / 2 LOW) — ALL FOLDED

1. **HIGH** SOS `key_sighted` ambiguity — an SOS Statement of Information is both vendor-filed and
   registry-held, so the registry's own record could unlock the bulk lane → per-lane definition:
   nothing held by/filed to the key's own registry ever qualifies (SOI facts feed address-match /
   filing-continuity instead); EIN lane's 990 stays qualifying (vendor-authored, distinct from the
   BMF anchor) (§4).
2. **MEDIUM** verifier downgrade lost the original position → `verifier.original_verdict` /
   `original_confidence` preserved; refutation rates reported by original class (§6).
3. **LOW** agreement denominator underspecified → positioned = verdict ∈ {same, different},
   fleet-unsure excluded by definition (§7 gate 2).
4. **LOW** leak check could false-flag person-name-shaped orgs (law firms, memorial foundations) →
   diff against an `allowed_org_name_set` incl. research-discovered aliases/DBAs, org names only (§3).

**Round-2 verdict: another-round-needed, but close** (single must-fix = the SOS ambiguity) → v3.

### Round 3 — 2026-07-01: 2 LOW nits — ALL FOLDED → **CONVERGED**

1. **LOW** compactor trusted agent-provided `researched_at` (clock skew could promote a worse row)
   → last-append-wins; log order is authority, timestamps are provenance (§3).
2. **LOW** person-data promise only covered emitted rows, not scratch/caches/manifests →
   transient-use rule: no person data in ANY durable artifact; all run artifacts pass the same
   redaction floor (§5.5).

**Round-3 verdict: CONVERGED** — "No critical/high/medium contract defects remain."
