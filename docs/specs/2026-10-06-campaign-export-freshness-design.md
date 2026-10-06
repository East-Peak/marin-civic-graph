# Campaign export freshness: export-due alarm, automatic preparation, freshness labels (CF5)

Goal 5 of 6 of the campaign-finance track (decision record: workspace
`decisions/2026-09-29-open-marin-campaign-finance-shape.md`). NetFile's yearly "Export Amended" ZIP sits behind
a Cloudflare Turnstile captcha, so only the operator can download it, by hand, in a browser. Nothing here
automates, bypasses or solves that captcha. This goal makes the operator's manual step loud when it is due, and
makes everything between "a ZIP landed in data/raw" and "a plan is ready to apply" automatic. Applying a plan to
the live graph stays a one-word approval ("apply").

Checked 2026-10-06: netfile.com serves no robots.txt (404, so nothing is disallowed) and the portal links no
terms of use. The no-captcha routes used here are the ones the public portal itself calls.

## 1. Effective inventory (`scripts/cf_inventory.py`)

Input: `data/raw/<source>/<YYYY-MM-DD capture>/<year>.zip`, the registry (`registry/netfile-sources.yaml`) and a
validation cache keyed by sha256.

- **Submitted**: every file under a capture dir. A dir whose name is not a real date, a future date, or a file
  not named `<year>.zip` for a year in `backfill_from..current year` is *landed but not ready*, with the reason
  ("rename CMAR_2026_Amended_Transactions.zip to 2026.zip").
- **Validated**: the same workbook check the normalizer runs (`campaign_ledger._check_workbook`: one .xlsx, the
  known sheets and columns, every row readable), plus the export's **latest observed report date** (max
  `Rpt_Date` over every sheet). An HTML page gets a plain reason ("an HTML page, not the export ZIP: the
  download failed or was blocked"). Results are cached by sha256 in the CF state.
- **Pinned pages**: a file matching a registry `unavailable_inputs` pin (capture, file, sha256) is unavailable
  coverage, as today. Pins describe those exact files only.
- **Selection** per source and year: the newest capture holding that year's file. If it validates (or is
  pinned), it is selected. If it does not, the year is **held**: never silently replaced by an older file.
  A newer capture may hold only some years; the others keep their older selection.
- **Gaps**: a year with no valid selected file (missing, pinned page, or held).
- **Confirmed unavailable**: a registry entry
  `confirmed_unavailable: [{year: "2019", confirmed: "2026-10-06", reason: "..."}]` (operator-written). Such a
  year's *missing coverage* is a warning, not a daily demand; it becomes due again (a retry reminder) 91 days
  after its `confirmed` date. Confirmation never suppresses a submission: an invalid file landed for that year is
  held and due like any other.
- `selection_id` = sha256 of the sorted selection (source, year, sha256 or status, capture date). It identifies
  what data/raw offers; the bundle actually prepared (after any fallback, section 3) has its own `bundle_id`,
  hashed over its complete effective manifest (source, year, sha256, original capture date, status).

## 2. Export-due alarm (`scripts/cf_export_due.py`)

A second Healthchecks.io check, **"Open Marin campaign export due"**, ping URL in `ops/launchd/weekly.env` as
`OPEN_MARIN_EXPORT_DUE_URL`. Every weekly run evaluates it, independently of the rest of the run: after a clean,
failed or refused run, and when the run lock is held (read-only, nothing persisted then). It pings
`<URL>/fail` with a plain-text body when anything is due, the plain URL (body: "nothing due" + warnings)
otherwise. "Today" is the America/Los_Angeles date.

Due rules per source and year (selected export age = today − its capture date):

| Rule | Due when |
|---|---|
| Current year | age > 7 days during Sep 1–Nov 15 of even years, else > 30 days |
| Previous year | age > 90 days |
| Older years within `backfill_from` | age > 365 days |
| API transaction hint | ≥1 transaction dated after the export's latest report date, within that year |
| API filing hint | ≥1 campaign filing filed after the export's capture date whose period ends in that year (no period: its filing year) |
| Gap | no valid selected file, unless confirmed unavailable (then warning; retry reminder after 91 days) |
| Landed but not ready | a submitted file failed validation (or a misnamed file/dir), with the reason |
| Prepared, awaiting approval | "export processed; plan ready at <path>; tell Claude 'apply'" until applied and published hashes match |
| Applied, awaiting publish | "applied; the next weekly run publishes it (nothing to do)" |
| Held preparation | the gate that held it, its reason, and the exact recovery action |

The calendar rules always run. The API hints only ever add due items: counts are positive hints, never proof of
currency (a same-count amendment is caught by the calendar or the filing hint).

**API** (base `https://netfile.com/api/public/sites/`), through an injected `fetch_json`, at most one request
per second (injected clock and sleep), per source:
- `api/filings/byDate?agencyCode=<AID>&startDate=<oldest selected capture + 1 day>&endDate=<today>&page=N
  &pageSize=100&isArchived=false&isOnlyCampaign=true` → `{filings: [{id, filingDate, periodEnd, …}],
  totalCount}`; at most 10 pages (a truncated listing is still a hint).
- for each year whose latest report date + 1 ≤ min(today, Dec 31): `api/SearchCampaignTransactions?aid=<AID>
  &query=&currentPage=1&pageSize=1&isArchived=false&dateStart=<latest report date + 1>&dateEnd=<year-12-31>`
  → `{items, totalCount, …}`; only `totalCount` is read.
Shapes are validated (types of `totalCount`, `filings`, each filing's `id`, `filingDate`, `periodEnd`); a
mismatch is "API shape changed". Only counts and filing ids are kept (ids capped at 20 per item); no
contributor field is read into anything persisted.

**Monitoring failures are main-heartbeat failures.** Missing or invalid alarm config (empty URL, unreadable
registry, a source without `agency_code`/`portal_url`), API unreachable or changed shape, a crash in the
evaluation, or a failed alarm ping each make the main run not clean (`/fail` with the reason). The alarm itself
still pings, on calendar rules only, when the API fails.

**Body**, per due item: agency, year(s), why, the portal URL, the "Export Amended" button, and the target path
`data/raw/<source>/<today>/<year>.zip`; then coverage warnings, then the API status line. Capped at 10,000 chars.

**Dry run**: `refresh_weekly.py export-due --dry-run` prints today's verdict and body against the live API,
without pinging, persisting or taking the lock. Without `--dry-run` it evaluates and pings (for testing the
check), still persisting nothing.

**Secrets**: both check URLs are secrets. `scrub()` removes each full URL, its query, every individual query
value (raw and percent-decoded), and every path segment of ≥ 8 characters (raw and decoded) from every sink (step logs, state.json, digests, CF state, ping bodies, exception text,
stdout/stderr); `_step()` strips both from child environments. `weekly.env.example` and `install.sh`
validation gain the new variable. The registry gains `name`, `agency_code` and `portal_url` for both sources
(increment 1), so the alarm's configuration is complete on the first run.

## 3. Preparation (`scripts/cf_prepare.py`)

Runs inside `weekly`, under its lock, after the main stage/load/publish/snapshot, and only when the graph is
settled (no unresolved or failed load in this run). It never writes the live graph. Outputs go under
`$OPEN_MARIN_CF_STAGING` (default `~/open-marin-staging/cf-refresh`), one dir per preparation
`<staging>/<run_id>/`. State: `data/ingest-runs/campaign-finance.json` (written atomically, scrubbed), holding
separately: `submitted` (every file seen: path, sha256, capture), `validated` (sha256 → ok, reason, latest
report date), `prepared` (bundle_id, run dir, config hash, baseline export sha256, outcome, gate, reason),
`applied` (bundle_id, verified against which export sha256, when) and `published` (bundle_id, published sqlite
sha256, when).

Each run:
1. Inventory (above). Nothing selected anywhere → nothing to do.
2. Fresh read-only export (`export_live_graph.py --backup --out-dir <prep>/export`): its sha256 is the graph
   baseline. Recorded attestations are never trusted on their own: every run re-verifies against *this* export
   and the *current* published SQLite.
3. **Applied** = `cf_migration_plan.py --check-live <export> --bundle <b>` passes now, for the newest prepared
   bundle or the last applied one (re-checked; a graph restore invalidates it). **Published** = the current
   `data/exports/public-substrate.sqlite` meta `campaign_freshness.bundle_id` equals it (re-read every run).
4. No-op only when (a) the effective bundle is currently applied and published, or (b) a *successful*
   preparation exists for the same (bundle_id, configuration fingerprint, baseline sha256). Held outcomes are
   retried every run. Otherwise (new selection, stale plan after a weekly load, changed configuration, a
   transient or held failure) → prepare again from the same files, no new download.
5. **Bundle**: a complete replacement across both sources and every year the applied manifest represents.
   Absence never means retirement: a source with held years, or a year the applied manifest has but data/raw no
   longer offers, keeps the applied manifest's file for it (its immutable staging copy, re-hashed). With no
   applied manifest (first run), the full current selection is tried; if it is already applied (check-live) it
   becomes the applied manifest (bootstrap). If a fallback is needed and none exists, nothing is prepared, it
   fails closed and the alarm names the recovery (fix the held file; or land the exports the live graph was
   built from).
6. **Configuration fingerprint**: sha256 over the netfile and node-type registries, the contributor review
   decisions, the attach overlay, and the code of every script in the chain (ledger, normalizer, contributor
   detail, exposure policy, public props, plan, bake, scan). Taken at the start and the end of a preparation;
   a change mid-run is a transient failure.
7. Selected files are copied to `<prep>/raw/<source>/<prep date>/<year>.zip` (copy re-hashed), with a staging
   registry that re-keys pins to that dir and lists the bundle's years (`years:` — new optional registry key the
   normalizer honours), and `<prep>/selection.json` records each file's original path, sha256, capture date and
   status.
8. Gates, each named when it holds the preparation:
   - **normalize** `normalize_campaign_finance.py --all` into `<prep>/bundle`;
   - **reconcile**: every source's `reconciliation.json` has 0 errors, 0 `mismatched`, 0 `ambiguous`
     (`missing_oracle` counts are reported, not held);
   - if `--check-live` of the export against the new bundle passes, the bundle is already **applied**: stop here;
   - **plan** `cf_migration_plan.py --baseline <export> --bundle <bundle> --out <prep>/plan`, exit 0 (its
     candidate verification is the plan-verification gate);
   - **bake** baseline (from the export) and candidate (from `plan/candidate`) with one frozen configuration
     copied into `<prep>/config/` first (node-type registry, attach overlay);
   - **scan** `scan_public_substrate.py` gates A/B/C and controls PASS. Unexplained findings hold; no
     explanation file is ever generated.
   When more than one source changed and a data gate fails, each changed source is retried alone (others at
   their applied selection) so the passing one still prepares; a combination that only fails together holds all.
   Export/bake timeouts and crashes are transient: retried next run and reported on the main heartbeat.
9. `<prep>/summary.md`: flows added / retired / changed, new actors by type, amount deltas per flow type, scan
   verdict, the recovery or apply instruction.

**Scanner fixes** (found on the 2026-10-01 refresh, `SCAN-EXPLAINED.md`): gate B keyed `search_fts` streams by
rowid, so inserted records renumbered every later row (197,742 false findings). Streams are now keyed by node
id; records added or removed (by node id, present in one bake's `nodes` and not the other) are reported
separately (`gate_b_added_records`, `gate_b_removed_records`), not as changed streams; an FTS row with no node
behind it is still a finding. Gate A keeps its rowid-keyed streams for its unchanged-text hash; only gate B's
comparison is re-keyed. Detector and needle scans still run over added records' text. The contact detectors no longer run over record-id columns (`nodes.id`,
`browse_rows.id`, `edges.source/target`, `identity_links.source/target`), and a row's own id is masked out of
its other text (a browse label that is the id) before detection.

Ordering inside `weekly`: stage → load → export → bake (with the CF bundles the state names, each verified by
the bake itself against its own export) → publish → snapshot → CF preparation (reads the just-published
artifact for "published") → export-due alarm → main heartbeat. On the very first run there is no CF state, so
that run's artifact carries no freshness key; the preparation bootstraps the applied manifest and the next
weekly run publishes it (one week, once; the alarm says "applied; the next weekly run publishes it").

## 4. Freshness labels

`bake_public_substrate.py --campaign-bundle <dir>` (repeatable) writes meta `campaign_freshness` from the first
bundle that `check_live` verifies against the export being baked: per source its name, jurisdiction, latest
report date observed (max `rpt_date` in the bundle's filings), the export date per year (capture date of each
selected file), unavailable years and held years, plus the `bundle_id`. No bundle verifies → no key, and the
surfaces say campaign coverage dates are unavailable for this build. `weekly` passes the newest prepared bundle,
then the applied one; the published artifact's `bundle_id` is what "published" means.

App: a `CampaignFreshness` block on every campaign surface (name views, committee ranking, /contributions,
committee and MoneyFlow facts), per source: "Latest report date observed: <date>", "Exports: 2019–2024 on
2026-04-14, 2025–2026 on 2026-10-01", "Novato: 2019–2021, 2025–2026 not available". Committee and MoneyFlow
pages show their own jurisdiction's source; the cross-committee surfaces show every source. Never "filings
through". An artifact without the key (the currently published one) renders the unavailable line.

## 5. Increments (each reviewed by Codex before commit, each under ~1,500 changed lines)

1. Alarm + secrets: `cf_inventory.py` (selection, validation, gaps), `cf_export_due.py`, `refresh_weekly.py`
   wiring + `export-due` CLI, env example, install.sh, secret-leak tests.
2. Preparation + scanner fixes: `cf_prepare.py`, normalizer `years:`, bake `--campaign-bundle` meta, alarm
   items for prepared/applied/held, weekly wiring, real-data rehearsal in staging.
3. Freshness labels: app reader + component on each surface, rendered tests; ops README and this spec's
   operator section.

Out of scope: captcha automation, ingesting search-API transactions, automatic application, identity work,
corrections route, San Rafael, UI redesign.
