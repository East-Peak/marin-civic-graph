# San Rafael in the weekly run: crosswalk identity, no-overwrite load

San Rafael City Council's Meetings (283 as of 2026-10-17, 2010-02-16 onward) were built by the wave-01
one-off scripts with hand-made ids, `meeting-{date}-san-rafael-city-council[-suffix]`. The ProudCity
adapter emits `meeting-san-rafael-city-council-{slug}`. So San Rafael is `identity: crosswalk-required`
in registry/proudcity-sources.yaml. Its ids come from a reviewed crosswalk or stay the adapter's own,
and its load never writes to anything that already exists.

| Piece | Where |
|---|---|
| Crosswalk (listing slug → existing Meeting id) | registry/crosswalks/san-rafael-city-council.json |
| Generator / validator | scripts/crosswalk.py |
| Ingest identity mode | scripts/ingest.py (`run_source`) |
| No-overwrite load, Record resolver | scripts/guarded_load.py, scripts/normalize_meetings.py |
| Weekly wiring (report, holds) | scripts/refresh_weekly.py (`load`, `_take_load_report`) |
| Rehearsal, check-loaded | scripts/crosswalk_rehearsal.py |

## How a Monday goes

1. **Stage.** `ingest.py` loads the crosswalk before any request. If it is missing or invalid, the
   source ends `crosswalk_invalid` and nothing is fetched. Each meeting's id becomes its crosswalk
   target, or stays the adapter's own. Two meetings claiming one id end it `crosswalk_conflict`. The
   date/title identity map is never used for San Rafael. The capture and the ledger pin the crosswalk's
   sha256.
2. **Load.** `normalize_meetings.py --load` takes San Rafael through `guarded_load`, in one transaction
   under the run lock:
   - It **creates** new Meetings, new Records, and the edges that touch them.
   - It **never writes** to an existing node or relationship: no property, label, `display_label` or
     `promotion_state`. The org/place stubs are included. Differences are only counted
     (`protected_differences` in the load report).
   - It **skips** an edge between two existing nodes (counted in `skipped_edges`).
   - Each artifact's Record is the meeting's established Record of that kind, then another meeting's
     Record for the same url (only for a new meeting), then a new `record-san-rafael-city-council-<meeting>-<art>`.
3. **Report.** The load writes `data/ingest-runs/<run>/load-reports/san-rafael-city-council.<n>.json`.
   `loaded` → the source is loaded. `held` → nothing of San Rafael was written. The source shows as
   FAILED in the digest's Failures with the hold reasons, the heartbeat goes `/fail` (an email), and
   every other source loads and publishes as usual.

## When San Rafael is held

The digest names the reason, and the report lists every hold:

| Reason | Meaning | What to do |
|---|---|---|
| `artifact_url_changed` | A meeting's agenda/packet/minutes now points at a different url than its existing Record (A→B). | Look at both PDFs. If B replaces A, that's a reviewed migration (update the Record's url). Never let the load mint a second Record. |
| `artifact_url_on_other_record` | An existing meeting's artifact url belongs to another meeting's Record. | Check the two meeting pages; usually a city posting error. |
| `artifact_url_shared`, `artifact_url_shared_across_kinds` | One url on two artifact types (one meeting, or across new meetings). | Usually a city posting error; wait for a fix or hold the source manual. |
| `crosswalk_target_mismatch`, `duplicate_native_meeting`, `crosswalk_entry_missing`, `crosswalk_disagrees` | The crosswalk and the graph disagree (a hand edit, a lost entry, an id that already exists). | Regenerate (below) and read the conflicts. Never hand-edit an entry to make a hold go away. |
| `crosswalk_changed`, `crosswalk_invalid`, `policy_mismatch` | The crosswalk or the registry changed between stage and load. | Stage a fresh run. |
| `missing_node` | A stub (org-san-rafael-city-council, place-san-rafael) is gone. | Investigate; the load never creates stubs. |

## Regenerating the crosswalk

Take a fresh read-only export first (`scripts/export_live_graph.py --out-dir <staging>`) and a saved
listing (the live page through the robots gate). Then:

```
python scripts/crosswalk.py generate --source san-rafael-city-council \
  --export <export dir> --listing <listing.html> --report <staging>/crosswalk-report.json [--write]
```

It is a dry run unless `--write` is given, and it never writes when there are conflicts. Entries are
append-only: an established entry survives every regeneration, including meetings that have left the
listing. Deleting or reassigning one is a conflict; doing it means a separate, reviewed migration.
Meetings created by an earlier weekly load show up as `native` and never get an entry.

Never auto-matched (Stuart's call, as of 2026-10-17):
- graph-only 2024-08-19 (no `meeting_date`, no page url) and 2024-12-16 (no page url);
- listing-only 2023-05-08 "Special (Revised)" and 2025-03-17 "Special & Regular". These load as new
  Meetings; the second shares the wave-01 2025-03-17 study session's minutes PDF, so its Record is
  reused, not duplicated.

## Rehearsal (staging only, no graph writes)

```
python scripts/crosswalk_rehearsal.py rehearse --source san-rafael-city-council \
  --export <fresh export dir> --work ~/open-marin-staging/sr-weekly/rehearsal-<date> \
  --identity-cache data/ingest-runs/meeting-identity.json
```

The rehearsal runs the real `refresh_weekly.stage` → `ingest.py` → adapter → robots gate chain, then
the real `refresh_weekly.load`, whose meeting step runs against a fake graph seeded from the export.
The first run fetches live and records every response. Three replays follow with a frozen clock:
populated identity cache, second identical run, and a later week. It writes `rehearsal.md` and exits 0
only if every check passes.

## After a real Monday run: check-loaded

**With the agenda-items stage on** (and it ran in that run: `<run>/agenda-items/pre/complete.json` exists), a
live export after the run also holds the stage's AgendaItems and their PART_OF_MEETING / EVIDENCED_BY edges, which
the meeting plan does not, so check-loaded would FAIL on them. Check the meeting load against the stage's own
pre-stage export instead (a full `--backup` export the run took under its lock, after the loads and before the
stage), then check the stage itself. No lock or live export is needed:

```
cd ~/projects/marin-civic-graph && RUN=<run id> \
  && .venv/bin/python scripts/crosswalk_rehearsal.py check-loaded $RUN --source san-rafael-city-council \
       --post-export data/ingest-runs/$RUN/agenda-items/pre \
  && .venv/bin/python scripts/crosswalk_rehearsal.py check-loaded $RUN --agenda-items
```

Without the stage in that run, take the post-export and run check-loaded together **while holding the run lock**, so no writer
(a weekly run, votes apply) can land between them:

```
cd ~/projects/marin-civic-graph && RUN=<run id> \
  && set -a && . ops/launchd/weekly.env && set +a && export NEO4J_URI=bolt://localhost:7688 \
  && .venv/bin/python - <<EOF
import os, subprocess, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from run_lock import run_lock
assert os.environ["NEO4J_URI"] == "bolt://localhost:7688" and os.environ.get("NEO4J_DATABASE") == "neo4j"
post = Path.home() / "open-marin-staging/sr-weekly" / "post-$RUN"
with run_lock(Path(".").resolve()):  # RunLockHeld = a run is in progress: retry later
    subprocess.run([".venv/bin/python", "scripts/export_live_graph.py", "--backup", "--out-dir", str(post)], check=True)
    sys.exit(subprocess.run([".venv/bin/python", "scripts/crosswalk_rehearsal.py", "check-loaded", "$RUN",
                             "--source", "san-rafael-city-council", "--post-export", str(post)]).returncode)
EOF
```

check-loaded binds itself to that run's pinned backup, capture, crosswalk and load report(s). It
refuses if any later run attempted a load. It re-plans the load on the backup and compares:

- new San Rafael nodes and every relationship touching San Rafael's nodes against the plan, exactly;
- every pre-existing San Rafael Meeting/Record (labels, every property), unchanged;
- the shared stubs, on the properties San Rafael's normalizer would write. Other loaders legitimately
  rewrite e.g. `place-san-rafael.source` every week.

Exit 0 = PASS. 1 = FAIL, or HELD (nothing of San Rafael loaded). 2 = refused (inputs not bound to the run).

## Activation (the flip)

San Rafael is `schedule: manual` until the switch to `weekly` is merged, which needs:

1. the 2026-10-19 weekly run inspected: digest/state clean, published, and B2's `check-published`
   passed (that run still runs the pre-crosswalk canonical checkout; the point is that publication is
   unaffected before San Rafael is switched on);
2. the flip rebased on a freshly fetched main and re-gated (pytest + `cd app && npm run verify`),
   then pushed. Record the exact SHA you gated and pushed;
3. the canonical checkout (which the LaunchAgent runs) fast-forwarded to **exactly that SHA, while
   holding the run lock**, acquired as refresh_weekly does. The lock file is never deleted or replaced.
   If the lock is held, a run is in progress: wait. Holding the lock is also the proof that no run is
   in progress while the checkout changes.

```
cd ~/projects/marin-civic-graph && SHA=<the full gated, pushed sha> && .venv/bin/python - <<EOF
import subprocess, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from run_lock import run_lock
git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
with run_lock(Path(".").resolve()):  # also the proof that no run is in progress
    if git("branch", "--show-current") != "main" or git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("the canonical checkout is not a clean main: stop")
    git("fetch", "origin", "main")
    if git("rev-parse", "origin/main") != "$SHA":
        sys.exit("origin/main moved since the gate: re-gate first")
    if subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "$SHA"]).returncode:
        sys.exit("HEAD is not an ancestor of the gated sha: stop")
    git("merge", "--ff-only", "$SHA")
    if git("rev-parse", "HEAD") != "$SHA":
        sys.exit("HEAD is not the gated sha after the fast-forward: stop")
    print("canonical checkout at $SHA")
EOF
```

Then hand the check-loaded snippet above to Claude in Stuart's planning tab, to run on the first weekly
run after the flip (its run id: the first `data/ingest-runs/<run id>/` whose state lists
`san-rafael-city-council` in `loaded`).

## Writer boundary

The guarded load's checks (slugs, artifact urls) hold because every graph writer serializes on the
ingestion run lock (data/ingest-runs/.lock): the weekly run, ingest.py, and votes apply
(`votes_apply.py apply` takes it on the canonical root). The load is also one transaction. Between a
Monday run and its check-loaded export, take nothing else: the check-loaded snippet holds the lock.

Mill Valley (registry/civicplus-sources.yaml) is held manual for the same id mismatch. It can follow
with its own crosswalk file and `identity: crosswalk-required`. The identity mode, load, rehearsal and
check-loaded are source-generic; the generator's listing parser (`extract_meeting_urls`) and the
rehearsal's registry copy are ProudCity's, so a CivicPlus source needs those two pieces generalized first.
