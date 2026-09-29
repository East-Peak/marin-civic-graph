# Weekly ingestion LaunchAgent

`cc.eastpeak.openmarin-refresh-weekly.plist` runs `scripts/refresh_weekly.py stage` every Monday at 05:00 on
this machine (repo `/Users/tammypais/projects/marin-civic-graph`, operator graph `bolt://localhost:7688`).
Nothing in the repo installs it. Installing it is the operator's call, made with `install.sh`.

`stage` fetches every weekly source, floors each one against its last good run, and stages the results
under `data/ingest-runs/<run_id>/`. It then writes `digest.md` and stops at `awaiting_load_approval`. It never
loads into Neo4j and never publishes. Those two steps stay manual gates:

```sh
.venv/bin/python scripts/refresh_weekly.py status            # latest run's state and digest path
.venv/bin/python scripts/refresh_weekly.py load <run_id>     # needs NEO4J_URI/USER/PASSWORD in your shell
.venv/bin/python scripts/refresh_weekly.py publish <run_id>  # swaps data/exports/staging/ into data/exports/; no deploy
```

## Pieces

| File | Role |
|---|---|
| `cc.eastpeak.openmarin-refresh-weekly.plist` | The job. No `KeepAlive`, no `RunAtLoad`, no secrets. |
| `run-weekly-stage.sh` | What launchd runs: rotates logs, sources `weekly.env`, runs `stage`, returns its exit code. |
| `weekly.env` | Operator-local and gitignored. It holds `OPEN_MARIN_HEARTBEAT_URL` and `COURTLISTENER_API_TOKEN`. Copy it from `weekly.env.example`, then `chmod 600`. |
| `install.sh` | Verifies, lints, copies to `~/Library/LaunchAgents/`, bootstraps. `--uninstall` reverses it. |

**Heartbeat.** When `stage` has persisted `awaiting_load_approval` and its complete digest, it pings
`OPEN_MARIN_HEARTBEAT_URL`, the Healthchecks.io check **"Open Marin weekly review ready"**.

- A green check means a review is available, not that every source passed. A partial success pings too.
- A crash, a preflight failure, a run where every source failed, or a lock refusal never pings.
- A failed ping is recorded in `state.json` and the digest. It never changes the run's status or exit code.
- The URL embeds the check's secret. It never appears in a log, `state.json`, or a digest, and no step inherits it.

**Timeouts.** Every step has a wall-clock ceiling (`STEP_TIMEOUTS` in `scripts/refresh_weekly.py`). The whole
default stage is under 3 hours. When a step exceeds its ceiling, it is killed and its source fails with
"timed out after Ns". To override a ceiling, set `OPEN_MARIN_TIMEOUT_<STEP>=<seconds>` in `weekly.env`.
Each fetch also has its own network timeout. Timeouts, dropped connections and 5xx responses are retried up to
3 times. A 4xx response is never retried.

**Logs.** All logs go to `data/ingest-runs/launchd/`, which `install.sh` pre-creates:

- `weekly-stage.log` is the wrapper's output and `stage`'s output.
- `launchd.{out,err}.log` fill only if the wrapper itself can't start.

A log that reaches 5 MiB rotates to `.1` through `.3`. Each step's own log is in `<run>/logs/`.

## Healthchecks.io check (one-time)

1. Create a check named **Open Marin weekly review ready**, with schedule type **Cron**:
   - expression `0 5 * * 1`
   - time zone `America/Los_Angeles`
   - grace time **6 hours**

   The DOWN email then goes out at Monday 11:00 Pacific if no run reached review.
2. Use email notifications only: one email on DOWN and one on recovery. Account → Settings → Email Reports →
   "Ongoing reminders" is set to **daily**, so a DOWN email deleted unread comes back the next day until the job recovers.
3. Copy the check's ping URL into `ops/launchd/weekly.env` as `OPEN_MARIN_HEARTBEAT_URL=...`, then `chmod 600 ops/launchd/weekly.env`.

## Installing (operator only)

```sh
ops/launchd/install.sh              # refuses without a private weekly.env holding the heartbeat URL
ops/launchd/install.sh --uninstall  # bootout + remove the installed plist; weekly.env and logs stay
```

`install.sh` refuses to run from a checkout other than the one the plist names. If the repo moves, update
the plist's paths first.

## Acceptance (before calling monitoring operational)

1. **Controlled run under launchd.** Run `launchctl kickstart gui/$(id -u)/cc.eastpeak.openmarin-refresh-weekly`.
   Don't pass `-k`, which kills a running instance. The stage takes about 15 minutes.
   `launchctl print gui/$(id -u)/cc.eastpeak.openmarin-refresh-weekly` shows its state and last exit code.
   Exit code 1 with some sources failed is a partial success, not a failure.
2. **State and digest.** `.venv/bin/python scripts/refresh_weekly.py status` shows the new run at
   `awaiting_load_approval`. Its `digest.md` lists every source. Its `state.json` has `"heartbeat": {"ok": true, ...}`.
3. **Logs.** In `data/ingest-runs/launchd/weekly-stage.log`, check that:
   - the run has matching `starting` and `exited N` lines;
   - there is no `WARNING` about `weekly.env`;
   - the heartbeat URL appears nowhere.

   `launchd.err.log` should be empty.
4. **Heartbeat receipt.** The Healthchecks.io check shows a ping at the time of the run and is **up**.
5. **Missed-heartbeat email.** Temporarily switch the check to a Simple schedule with a 1-minute period and
   1-minute grace. Wait for the check to go **down**, then confirm that exactly one DOWN email arrived.
6. **Recovery.** Kickstart the job again (step 1). When it reaches review, the check goes **up**. Confirm that
   exactly one recovery email arrived.

   Then restore the cron schedule (`0 5 * * 1`, `America/Los_Angeles`, 6-hour grace).

Sleep defers a calendar job until wake. Power-off and logout do not: the external deadline is what catches
those.

Not built here yet (see the monitoring verdict):

- digest delivery through Tammy
- the persistent-source escalation
- approval reminders
- the public `/api/health` and provenance manifest
