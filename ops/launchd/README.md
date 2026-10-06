# Weekly ingestion LaunchAgent

`cc.eastpeak.openmarin-refresh-weekly.plist` runs `scripts/refresh_weekly.py weekly` every Monday at 05:00 on
this machine (repo `/Users/tammypais/projects/marin-civic-graph`, operator graph `bolt://localhost:7688`).
Nothing in the repo installs it. Installing it is the operator's call, made with `install.sh`.

`weekly` runs unattended; the checks are the gate (docs/specs/2026-09-29-automatic-weekly-refresh.md):

1. **stage**: fetch every weekly source, floor each one against its last good run, stage and fingerprint it.
2. **load**: back up the whole graph to `data/exports/backups/pre-load-<run_id>/`, load the sources that
   passed, then reconcile, export and bake (budget and URL-collision guards).
3. **publish**: swap the bake into `data/exports/` (no deploy; `rollback <run_id>` undoes it).
4. **snapshot**: commit `normalized/` + `extracted/` to the private data repo and push.
5. **campaign preparation**: every campaign export landed in `data/raw/` is prepared, read-only against the
   graph, up to a plan ready to apply (see "When the export-due email arrives").
6. **export-due alarm**: the second check is pinged, whatever happened above.
7. **heartbeat**: one ping, success only if all of that was clean.

A source that fails its floors is held (its last good data stays) and the rest still publish. `weekly` will
not load while an earlier run is `load_failed`. The manual subcommands stay, for recovery:

```sh
.venv/bin/python scripts/refresh_weekly.py status            # latest run's state and digest path
.venv/bin/python scripts/refresh_weekly.py load <run_id>     # needs NEO4J_URI/USER/PASSWORD/DATABASE in your shell
.venv/bin/python scripts/refresh_weekly.py publish <run_id>  # swaps data/exports/staging/ into data/exports/; no deploy
.venv/bin/python scripts/refresh_weekly.py rollback <run_id> # restores what was live before that publish
.venv/bin/python scripts/refresh_weekly.py rebake <run_id>   # redo reconcile/export/bake after a post-load failure
```

## Pieces

| File | Role |
|---|---|
| `cc.eastpeak.openmarin-refresh-weekly.plist` | The job. No `KeepAlive`, no `RunAtLoad`, no secrets. |
| `run-weekly.sh` | What launchd runs: rotates logs, sources `weekly.env`, runs `weekly`, returns its exit code. |
| `weekly.env` | Operator-local and gitignored. It holds `OPEN_MARIN_HEARTBEAT_URL`, `OPEN_MARIN_EXPORT_DUE_URL`, `COURTLISTENER_API_TOKEN` and `NEO4J_USER`/`NEO4J_PASSWORD`/`NEO4J_DATABASE`. Copy it from `weekly.env.example`, then `chmod 600`. |
| `install.sh` | Verifies, lints, copies to `~/Library/LaunchAgents/`, bootstraps. `--uninstall` reverses it. |

**Heartbeat.** `weekly` pings `OPEN_MARIN_HEARTBEAT_URL`, the Healthchecks.io check **"Open Marin weekly
refresh"**, once, at the end. Only `weekly` pings; the manual subcommands never do.

- **Clean** (published, every source passed, snapshot pushed, all persisted): the plain URL. No email.
- **Anything else** (a held source, preflight, load, bake or publish failure, a snapshot failure, a lock
  refusal, a crash): `<URL>/fail`. The check goes down and emails at once, then daily until a clean run.
- **No run at all** (Mac off, job not loaded): no ping, so the check's grace deadline emails.
- The ping's body says what happened: the run id and status, held source ids, the error, the digest path.
  Healthchecks keeps it with the event. It never carries a log tail.
- A failed ping is recorded in `state.json` and the digest. It never changes the run's status.
- Secrets (both check URLs, graph password, API tokens) are scrubbed from every step's output before it is
  logged, recorded, or pinged, and no step inherits either URL.
- Monitoring failures of the export-due alarm also fail this check: `OPEN_MARIN_EXPORT_DUE_URL` missing or
  invalid, `registry/netfile-sources.yaml` incomplete, the NetFile API unreachable or changed, or the alarm's
  own ping failing. So does a campaign preparation that crashed or timed out (it is retried next week).

**Timeouts.** Every step has a wall-clock ceiling (`STEP_TIMEOUTS` in `scripts/refresh_weekly.py`). The stage
ceilings total under 3 hours; a normal week's whole run takes under an hour. When a step exceeds its ceiling, it is killed and its source fails with
"timed out after Ns". To override a ceiling, set `OPEN_MARIN_TIMEOUT_<STEP>=<seconds>` in `weekly.env`.
Each fetch also has its own network timeout. Timeouts, dropped connections and 5xx responses are retried up to
3 times. A 4xx response is never retried.

**Logs.** All logs go to `data/ingest-runs/launchd/`, which `install.sh` pre-creates:

- `weekly.log` is the wrapper's output and the run's output.
- `launchd.{out,err}.log` fill only if the wrapper itself can't start.

A log that reaches 5 MiB rotates to `.1` through `.3`. Each step's own log is in `<run>/logs/`.

## Healthchecks.io check (one-time)

1. Create a check named **Open Marin weekly refresh**, with schedule type **Cron**:
   - expression `0 5 * * 1`
   - time zone `America/Los_Angeles`
   - grace time **6 hours**

   A failed run emails at once (its `/fail` ping); a run that never reports emails at Monday 11:00 Pacific.
2. Use email notifications only: one email on DOWN and one on recovery. Account → Settings → Email Reports →
   "Ongoing reminders" is set to **daily**, so a DOWN email deleted unread comes back the next day until the job recovers.
3. Copy the check's ping URL into `ops/launchd/weekly.env` as `OPEN_MARIN_HEARTBEAT_URL=...`, then `chmod 600 ops/launchd/weekly.env`.

## Second check: "Open Marin campaign export due" (one-time)

NetFile's yearly "Export Amended" download sits behind a captcha: only you can fetch it, by hand. This check
emails you whenever you need to.

1. Create a check named **Open Marin campaign export due**, schedule type **Cron**, expression `0 5 * * 1`,
   time zone `America/Los_Angeles`, grace time **6 hours** (the same as the weekly run: it is pinged by it).
2. Email notifications only, with the account's **daily** "Ongoing reminders" (the same setting as above): while
   anything is due the check stays down and the reminder comes back every day.
3. Copy its ping URL into `ops/launchd/weekly.env` as `OPEN_MARIN_EXPORT_DUE_URL=...` (`chmod 600` stays).
   `install.sh` refuses to install without it.

Every weekly run pings it: `<URL>/fail` with the list of what to do when anything is due, the plain URL when
nothing is. `.venv/bin/python scripts/refresh_weekly.py export-due --dry-run` prints today's verdict (it reads
the NetFile API, about one request a second) without pinging or writing anything.

## When the export-due email arrives

The email lists, per agency, each year due and why (the export's age, NetFile transactions or filings newer
than it, no export on file), the portal link and the exact file to save. For each year listed:

1. Open the portal link (Marin County: https://netfile.com/public/CMAR/campaign, Novato:
   https://netfile.com/public/NVO/campaign). Choose the year, click **Export Amended**, and complete the
   captcha. Never use "Export" (unamended) and never automate this step.
2. Save the ZIP exactly where the email says: `data/raw/<source>/<today>/<year>.zip`, for example
   `data/raw/marin-county-campaign-finance/2026-10-12/2026.zip`. The folder is today's date (`YYYY-MM-DD`); the
   file is the year (rename `CMAR_2026_Amended_Transactions.zip` to `2026.zip`). One folder may hold just the
   years you downloaded; older folders stay as they are.
3. Nothing else. The next weekly run (Monday 05:00) checks each file, prepares everything up to a plan, and
   emails again:
   - **"landed but not ready"** (`... was not used: an HTML page, not the export ZIP`): the download failed or
     was blocked. Download that year again into a new dated folder. A bad newest file is never skipped in favour
     of an older one.
   - **"export processed; plan ready at <path>; tell Claude 'apply'"**: read the summary next to the plan
     (flows added, retired and changed; amounts; the privacy scan). Tell Claude "apply": it applies the plan to
     the operator graph by its procedure (fresh export must equal the plan's baseline, backup, one transaction,
     post-load check). The item stays until the next weekly run has published it.
   - **"held at <gate>"**: a gate stopped it (normalize, reconcile, plan, coverage, scan), with the reason and
     the recovery action. Tell Claude; nothing is ever applied or excepted automatically.
   Preparations go to `~/open-marin-staging/cf-refresh/<run>/` (override with `OPEN_MARIN_CF_STAGING`, never
   inside the repo); the state is `data/ingest-runs/campaign-finance.json`.

**When NetFile has no export for a year** (the portal offers none, or only an error page), record it in
`registry/netfile-sources.yaml` under that source:

```yaml
    confirmed_unavailable:
      - {year: "2025", confirmed: "2026-10-12", reason: "the portal lists no 2025 export for this agency"}
```

That year then shows as a coverage warning instead of a daily demand, and comes back as a reminder 91 days
after `confirmed` (update the date when you have checked again). A file you later land for that year is still
judged on its own: a bad one is due.

## Installing (operator only)

```sh
ops/launchd/install.sh              # refuses without a private weekly.env holding the URL + graph credentials
ops/launchd/install.sh --uninstall  # bootout + remove the installed plist; weekly.env and logs stay
```

`install.sh` refuses to run from a checkout other than the one the plist names. If the repo moves, update
the plist's paths first.

## Acceptance (before calling monitoring operational)

For the export-due check, after it is created and its URL is in `weekly.env`: (a) a weekly run while anything
is due takes it **down** with an email listing the steps; (b) the next day's **daily reminder** arrives; (c)
once nothing is due a run brings it **up** with a recovery email; (d) with the check on a 1-minute Simple
schedule, a missed ping takes it **down** on its own (as in steps 5–6 below).


1. **Controlled run under launchd.** Run `launchctl kickstart gui/$(id -u)/cc.eastpeak.openmarin-refresh-weekly`.
   Don't pass `-k`, which kills a running instance. A normal week takes under an hour.
   `launchctl print gui/$(id -u)/cc.eastpeak.openmarin-refresh-weekly` shows its state and last exit code.
2. **State and digest.** `.venv/bin/python scripts/refresh_weekly.py status` shows the new run `published`.
   Its `state.json` has `"backup"`, `"snapshot": {"ok": true, ...}` and `"heartbeat": {"ok": true, ...}`, and
   the private data repo's `git log -1` is `data: snapshot at publish <run_id>`, pushed.
3. **Logs.** In `data/ingest-runs/launchd/weekly.log`, check that:
   - the run has matching `starting` and `exited N` lines;
   - there is no `WARNING` about `weekly.env`;
   - neither the heartbeat URL nor the graph password appears anywhere.

   `launchd.err.log` should be empty.
4. **Heartbeat receipt.** The Healthchecks.io check shows the ping, with its body, at the time of the run. A clean
   run leaves it **up**; any held source or failure leaves it **down** with an email naming the problem.
5. **Recovery email.** Switch the check to a Simple schedule with a 1-minute period and 1-minute grace, then
   kickstart the job again (step 1). A clean run's ping brings the check **up**; confirm one recovery email
   arrived. (Switching the schedule on a check that is already late marks it down *without* an alert, so that
   is not a test of the DOWN email. Proved 2026-09-29.)
6. **Missed-heartbeat email.** About 2 minutes after that ping, with no further ping, the check goes **down**
   on its own; confirm exactly one DOWN email arrived. The integration's "Last Notification" on the
   Integrations page shows each delivery.

   Then restore the cron schedule (`0 5 * * 1`, `America/Los_Angeles`, 6-hour grace).

Sleep defers a calendar job until wake. Power-off and logout do not: the external deadline is what catches
those.

Not built here yet (see the monitoring verdict):

- digest delivery through Tammy
- the persistent-source escalation
- the public `/api/health` and provenance manifest
