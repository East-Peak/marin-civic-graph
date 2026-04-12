# Decision Log

This is the repo-local running index of the highest-signal project decisions.

Use it as the fast recovery layer after compaction or context loss.

Detailed decision writeups still live in:

- `~/.openclaw/workspace/decisions/`

The rule is:

- workspace decision note = detailed rationale
- this file = compact running index
- repo docs = durable technical implementation notes

## 2026-04-12

- **Active projects need a repo-local running decision index**
  - Keep a compact `docs/decision-log.md` in the repo, with detailed rationale still living in workspace decisions.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-active-projects-need-repo-local-decision-log.md`

- **Validation checks are first-class review objects**
  - Add `ValidationCheck` to distinguish extraction gaps from source inconsistency.
  - First live use is San Rafael `Form 460` reconciliation and summary-rollup QA.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-validation-check-layer-for-reconciliation-and-anomaly-work.md`

- **Schedule A QA should anchor on official itemized and unitemized summary totals**
  - Do not compare extracted row sums only to the top-line filing total.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-form460-schedule-a-summary-should-anchor-qa.md`

- **Vice Mayor is a bounded role claim, not a separate seat**
  - Model it on top of a councilmember `SeatService`.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-12-san-rafael-vice-mayor-annual-role.md`

## 2026-04-11

- **Campaign and disclosure modeling starts with election, committee, candidacy, filing, and economic-interest disclosure**
  - Keep committees distinct from actors and filings distinct from filing records.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-11-campaign-disclosure-node-set.md`

- **Procurement uses agreement-centered modeling**
  - Keep `Procurement`, `Agreement`, `Amendment`, `Deliverable`, and `PerformanceReview` separate.
  - Detailed note: `~/.openclaw/workspace/decisions/2026-04-10-procurement-layer-node-set.md`

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
