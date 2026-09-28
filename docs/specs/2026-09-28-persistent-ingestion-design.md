# Persistent ingestion — design

**Date:** 2026-09-28 · **Status:** IN PROGRESS · **Input:** scraper health audit 2026-09-28
(operator scratchpad), restart-plan decisions (workspace `decisions/2026-09-28-open-marin-restart-plan.md`).

## Problem

Ingestion has only ever been run by hand, once per source (April–June 2026). Nothing is scheduled.
A read-only audit on 2026-09-28 found most sources healthy, but also:

- **Silent failures.** NetFile replatformed. The campaign-finance and Form 700 scrapers now get HTTP 200
  with zero rows and report success. `ingest_form700.py` would then **overwrite** good April data
  with empty files.
- **Unstable identity.** Granicus rows without a `clip_id`, and every Ross row, are keyed by row
  position (`…-{date}-row-{N}`). The same meeting gets a new id each run, and because loads MERGE on `id`,
  a schedule would pile up duplicate Meeting nodes.
- **Registry drift.** Fairfax has no 2025–26 coverage, CivicPlus Tiburon has been dead since 2016, Mill Valley
  moved domains, and San Rafael (the case-study city) was never registered.
- **Wrong tail.** `refresh_openmarin.py` predates the substrate. It never rebakes
  `public-substrate.sqlite`, and it runs paid embedding and LLM steps every time.

## Principles

1. **A run never makes data worse.** Every stage is written to a dated staging location. A source whose
   pull fails its floors is skipped and flagged, and the previous good data stays authoritative.
   Nothing overwrites good data with empty data.
2. **Silence is failure.** Every source declares floors: a minimum rows-versus-last-run ratio and a maximum
   age of the newest record. A pull that returns 200 but falls below a floor counts as a failed pull.
3. **Identity is stable across runs.** Source ids derive from source-native keys, or from a date plus
   normalized-title hash. They never derive from row position.
4. **Humans gate the irreversible steps.** Fetch, stage, normalize, diff and bake-preview are automated.
   Loading into the operator graph and publishing a new public artifact each wait for Stuart's approval.
5. **Paid steps are opt-in.** Embeddings and cluster naming feed the parked constellation and are removed
   from the weekly path.

## Tranches

| # | Tranche | Contents |
|---|---|---|
| I1 | Safety net | `scripts/ingest_guard.py`: per-source floors (row ratio versus last good run, newest-record age), a never-overwrite-on-empty write helper, and a run ledger (`data/ingest-runs/<date>.json`). Wired into `ingest.py`, the NetFile adapter and the Socrata permits ingester |
| I2 | Stable meeting IDs | Granicus rows without `clip_id` and Ross rows keyed on source-native id, or on date + normalized-title hash. A dry-run report lists orphaned ids already in the graph. **No graph mutation**: the dedupe itself is an operator-gated step |
| I3 | Registry fixes | Fairfax `agendas-town-council/` archive; retire CivicPlus Tiburon; Mill Valley `.gov` domain plus id reconciliation; promote San Rafael into `proudcity-sources.yaml` |
| I4 | Form 700 on the new NetFile API | `POST netfile.com/api/public/sites/api/searchfilings` (JSON, no captcha) replaces the dead ASP.NET scrape, keeping the output schema. Never overwrites on empty |
| I5 | Weekly runner | `scripts/refresh_weekly.py`: preflight → probe → fetch/stage → floors → normalize/diff → **gate: load** → reconciliation refresh → export → rebake → parity smoke → **gate: publish**. A LaunchAgent runs it weekly on the operator Mac. Email digest to stuart@eastpeak.cc is the end state |

## Manual and paid sources (by decision)

- **CA SOS bulk:** quarterly, $100, ordered by hand. The watchdog emails a reminder at 90 days.
- **NetFile campaign-finance export:** Cloudflare Turnstile blocks automated export. For now, a human downloads the yearly
  "Export Amended" ZIP into `data/raw/<src>/<date>/`. Planned: a new adapter on `api/SearchCampaignTransactions`,
  which needs a MoneyFlow id mapping because the JSON has no `Tran_ID`/`Filer_ID`.
