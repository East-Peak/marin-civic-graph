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
5. **heartbeat**: one ping, success only if all of that was clean.

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
| `weekly.env` | Operator-local and gitignored. It holds `OPEN_MARIN_HEARTBEAT_URL`, `COURTLISTENER_API_TOKEN` and `NEO4J_USER`/`NEO4J_PASSWORD`/`NEO4J_DATABASE`. Copy it from `weekly.env.example`, then `chmod 600`. |
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
- Secrets (the URL, graph password, API tokens) are scrubbed from every step's output before it is logged,
  recorded, or pinged, and no step inherits the URL.

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

## Installing (operator only)

```sh
ops/launchd/install.sh              # refuses without a private weekly.env holding the URL + graph credentials
ops/launchd/install.sh --uninstall  # bootout + remove the installed plist; weekly.env and logs stay
```

`install.sh` refuses to run from a checkout other than the one the plist names. If the repo moves, update
the plist's paths first.

## Acceptance (before calling monitoring operational)

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
