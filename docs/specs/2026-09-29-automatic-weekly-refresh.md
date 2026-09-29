# Automatic weekly refresh (I5c)

Supersedes the manual load/publish gates of I5b (docs/specs/2026-09-28-persistent-ingestion-design.md)
for the scheduled run. Decision: the operator does not approve each week; the checks are the gate, and
the operator is emailed only when something needs their attention.

## Command

`refresh_weekly.py weekly` — what the LaunchAgent runs (replacing `stage`), under one run lock:

1. `stage` (unchanged: preflight, fetch, floors, digest, fingerprints).
2. If the run reached `awaiting_load_approval`, and no earlier run is `load_failed` (its partial writes
   may be in the graph; the operator resolves it first): `load` — which now **always** backs up the whole
   graph first (`export_live_graph.py --backup`: every property kept, and the files must hold as many
   nodes and relationships as the graph, or it fails), for the manual command too. A failed backup fails
   the run before anything is loaded; a retried load keeps the first backup. Load keeps every I5b guard
   (staged bytes == loaded bytes, newer-run refusal, promote only after every load succeeds), then
   reconciles, exports and bakes (budget + collision guards). A crash after loading fails the run
   visibly; `rebake` reruns reconciliation unless it had already succeeded.
3. If the run reached `awaiting_publish_approval`: `publish` (unchanged atomic swap; `rollback` works).
4. If published: snapshot the private data repo (the git repo `data/normalized` and `data/extracted`
   symlink into). It must be on `main` with an empty index (never commit someone else's staged work);
   then `git add -- normalized extracted`, commit `data: snapshot at publish <run_id>` if anything is
   staged, `git push origin main`. Recorded in state as `snapshot: {ok, commit|error}`. A snapshot
   failure never changes the run's status (the publish stands); it makes the outcome not clean.
5. Report the outcome to the heartbeat and exit.

The manual subcommands (`stage`, `load`, `publish`, `rollback`, `rebake`, `status`) stay, for recovery.

## Outcome and alerting (Healthchecks.io)

One check, cron `0 5 * * 1` America/Los_Angeles, 6 h grace, email + daily reminders.

- **Clean** — published, every source passed, snapshot pushed: ping the URL. No email.
- **Anything else** — preflight failure, every source failing, a held (failed-floor) source, load or
  bake failure, publish refused, snapshot failure, lock held, crash: ping `<URL>/fail`. Healthchecks
  marks the check down and emails at once (not after the grace), with daily reminders until a clean run.
  A held source still publishes the sources that passed; it alerts because an unattended pipeline must
  not degrade silently.
- **No run at all** (Mac off, launchd broken, process killed): no ping; the grace deadline emails.

Only `weekly` pings. Manual subcommands never ping (the check means "the scheduled pipeline ran clean").

The ping carries a short plain-text body (Healthchecks stores it with the event): run id, final status,
the ids of failed/held sources, the run's error truncated to 300 chars, and the digest path. It never
carries log tails, the heartbeat URL (scrubbed), or URI credentials (redacted). Body ≤ 2 KB.

Secrets — `*PASSWORD*`, `*TOKEN*`, `*SECRET*`, `*API_KEY*` values and the heartbeat URL — are scrubbed
from every step's output before it is logged, recorded in state.json (failure reasons quote log tails),
printed, or pinged.

## Credentials

`load` needs `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` (preflight now checks all three, and
refuses a database other than `neo4j`: the loaders write to the default database, so a backup or export
of another would not be the graph they changed). They go in
the operator-local `ops/launchd/weekly.env` (chmod 600; install.sh verifies they are set). `NEO4J_URI`
stays in the plist.

## Launchd

`run-weekly-stage.sh` → `run-weekly.sh` (runs `weekly`); log `weekly.log`. Reinstall with install.sh.
Healthchecks check renamed "Open Marin weekly refresh".

## Timing

Measured: stage 15–28 min; a steady-state load + reconcile + export + bake under 2 min; the first full
permits load took ~2 h. Backup export ~20 s. Typical run < 45 min, well inside the 6 h grace.

## Review (Codex planning review, 2026-09-29)

Folded: database mismatch guard; verified lossless backup; first backup kept on retry; no automatic load
over a `load_failed` run; secret scrubbing at every sink; snapshot baseline checks; crash after loading
fails visibly; rebake reruns a failed reconciliation. Held source => `/fail` confirmed.

Deferred, with reasons:
- *Publish is four renames, not one pointer switch* — pre-existing I5b behaviour; the window is
  microseconds, the previous artifacts are kept, and nothing serves them publicly yet. Revisit at launch (T5).
- *Refetch floors allow slow shrinkage (100 → 91 → 83 → 76)* — pre-existing; a held-out baseline and edge
  floors belong with the persistent-source escalation.
- *No whole-run deadline* — an overlong run already alerts through the grace deadline, then recovers
  when its ping lands; a second clock adds nothing.
