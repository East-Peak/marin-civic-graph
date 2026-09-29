# Persistent ingestion — design

**Date:** 2026-09-28 · **Status:** I1–I5b SHIPPED; first weekly cycle staged → loaded → rebaked → published
2026-09-28 (sha 07a51c2a…). Adversarial review (1 P0 / 4 P1 / 9 P2) fixed. Weekly LaunchAgent + healthchecks.io
heartbeat built, **pending install** (operator step, ops/launchd/README.md). Monitoring design: workspace
decisions/2026-09-29-open-marin-ingestion-monitoring.md · **Input:** scraper health audit 2026-09-28
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

## I1 floors: baselines, errors and resets (2026-09-28 review fixes)

- **Baseline.** The row floor compares a pull with the **max** row count over the last 4 good runs in
  `data/ingest-runs/ledger.jsonl`, not the last run alone, so a slow weekly decline cannot compound.
- **One row count.** The ledger, the seed and the capture header all use the adapter's **pre-merge** row
  count (`pulled_rows` in the capture); `meeting_count` is post-merge. Pre-merge is what the adapter
  actually pulled, so it is the number that shows a broken pull.
- **Errors.** A pull with more adapter `errors` than the source's `floors.max_errors` (default 0) fails,
  however many rows it kept. A source with a known benign error raises `max_errors` in its registry entry
  with a comment naming the error.
- **Seeding** skips capture files whose name is not a date and captures holding categories the source's
  current `categories` config excludes.
- **Reset.** A rejected run never becomes a baseline, so a source whose scope legitimately shrank fails
  forever. After checking the smaller pull by hand, run
  `python scripts/ingest_baseline.py --reset <source_id> --reason "..." [--rows N]`. It appends an audited
  `reset` entry (reason, time, previous baseline; rows default to the latest pull) that starts a new
  baseline window.

## Manual and paid sources (by decision)

- **CA SOS bulk:** quarterly, $100, ordered by hand. The watchdog emails a reminder at 90 days.
- **NetFile campaign-finance export:** Cloudflare Turnstile blocks automated export. For now, a human downloads the yearly
  "Export Amended" ZIP into `data/raw/<src>/<date>/`. Planned: a new adapter on `api/SearchCampaignTransactions`,
  which needs a MoneyFlow id mapping because the JSON has no `Tran_ID`/`Filer_ID`.

## I5b — the weekly runner (design, 2026-09-28)

**Finding.** The live graph was never built through one pipeline. `build_graph_v2` projects only a small
slice (~6K of ~130K nodes). Most data enters through per-ingester `--load` paths: permits, Form 700 and
CourtListener each refetch-and-load in one call, while meetings load via `normalize_meetings --load`
from the staged capture. A gate that approves staged data and then loads a *fresh refetch* would load
something nobody reviewed.

**Rule: approved bytes == loaded bytes.** Each refetching ingester gains a load-only mode
(`--load-from <dir>`) that loads previously staged `nodes.jsonl`/`edges.jsonl` without fetching.

**Runner.** `scripts/refresh_weekly.py`, with three subcommands and state under `data/ingest-runs/<run_id>/`:

1. `stage` (automated, runs from a LaunchAgent). Steps:
   - Preflight (env, disk, the neo4j_target guard).
   - `ingest.py --all` for each meeting registry (I1 floors apply).
   - Stage permits, Form 700 and CourtListener into `<run>/staged/<name>/` via `--output-dir`. Floors
     compare staged row counts with the current `data/normalized` counts.
   - Write `<run>/digest.md`, covering per-source verdicts, row deltas, new-meeting counts and failures,
     plus `state.json` with status `awaiting_load_approval`.
   - Exit non-zero if any source failed; the passing ones remain approvable.
2. `load <run_id>` (the operator gate):
   - Refuses unless the state is `awaiting_load_approval`.
   - Promotes passing staged dirs into `data/normalized`.
   - Runs `normalize_meetings --source X --load` for accepted meeting sources and `--load-from` for the rest.
   - Runs `refresh_reconciliation.sh`, `export_live_graph.py`, and `bake_public_substrate.py` into
     `data/exports/staging/`.
   - Records the bake report and size budget, and sets status `awaiting_publish_approval`.
3. `publish <run_id>` (the operator gate): atomically swaps the staged sqlite and manifests into
   `data/exports/` and records the published artifact hash. It never deploys; deploying is the separate
   launch decision.

Every external step is an injectable command, so tests never touch the network or Neo4j. The weekly
LaunchAgent runs `stage` only.
